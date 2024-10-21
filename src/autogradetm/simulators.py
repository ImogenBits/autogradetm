from __future__ import annotations

import contextlib
import tomllib
from abc import abstractmethod
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, Self

from docker import DockerClient
from docker.models.containers import Container as DockerContainer
from docker.types import Mount

CODE = Path("/code/")
COMPILED = Path("/compiled/")
TMS = Path("/TMs/")


class Language:
    extension: ClassVar[str | tuple[str, ...]]
    docker_image: ClassVar[str]
    projectfile: ClassVar[str] | None = None

    _registry: ClassVar[dict[str, Self]] = {}
    _projectfiles: ClassVar[dict[str, Self]] = {}

    def __init_subclass__(cls) -> None:
        instance = cls()
        extensions = cls.extension if isinstance(cls.extension, tuple) else [cls.extension]
        for extension in extensions:
            cls._registry[extension] = instance
        if cls.projectfile:
            cls._projectfiles[cls.projectfile] = instance

    def build_commands(self, sources: list[Path], entrypoint: Path) -> Iterable[list[str]]:
        return []

    @abstractmethod
    def run_command(self, entrypoint: Path, base_path: Path) -> list[str]: ...

    @classmethod
    def identify(cls, file: Path, type: Literal["any", "code", "projectfile"] = "any") -> Self | None:
        if type in ("any", "code") and file.suffix in cls._registry:
            return cls._registry[file.suffix]
        if type in ("any", "projectfile"):
            if file.suffix in cls._projectfiles:
                return cls._projectfiles[file.suffix]
            if file.name in cls._projectfiles:
                return cls._projectfiles[file.name]


class Python(Language):
    extension = ".py"
    docker_image = "python:3.13"

    def run_command(self, entrypoint: Path, base_path: Path) -> list[str]:
        return ["python", CODE.joinpath(entrypoint).as_posix()]


class Java(Language):
    extension = ".java"
    docker_image = "maven:latest"

    def build_commands(self, sources: list[Path], entrypoint: Path) -> Iterable[list[str]]:
        yield ["javac", "-d", COMPILED.as_posix(), *(source.as_posix() for source in sources)]

    def run_command(self, entrypoint: Path, base_path: Path) -> list[str]:
        return ["java", "-cp", COMPILED.as_posix(), entrypoint.stem]


class C(Language):
    extension = ".c"
    docker_image = "gcc:latest"

    main_path = COMPILED.joinpath("main").as_posix()

    def build_commands(self, sources: list[Path], entrypoint: Path) -> Iterable[list[str]]:
        yield ["gcc", "-o", self.main_path, *(f.as_posix() for f in sources)]

    def run_command(self, entrypoint: Path, base_path: Path) -> list[str]:
        return [self.main_path]


class CPP(C):
    extension = ".cpp"

    def build_commands(self, sources: list[Path], entrypoint: Path) -> Iterable[list[str]]:
        for _, *args in super().build_commands(sources, entrypoint):
            yield ["g++", *args]


class CSharp(Language):
    extension = ".cs"
    projectfile = ".csproj"
    docker_image = "mcr.microsoft.com/dotnet/sdk:8.0"

    def build_commands(self, sources: list[Path], entrypoint: Path) -> Iterable[list[str]]:
        yield [
            "dotnet",
            "build",
            "--output",
            COMPILED.as_posix(),
            "--artifacts-path",
            COMPILED.as_posix(),
            entrypoint.parent.as_posix(),
        ]

    def run_command(self, entrypoint: Path, base_path: Path) -> list[str]:
        return ["dotnet", COMPILED.joinpath(f"{entrypoint.stem}.dll").as_posix()]


class Rust(Language):
    extension = ".rs"
    projectfile = "Cargo.toml"
    docker_image = "rust"

    def build_commands(self, sources: list[Path], entrypoint: Path) -> Iterable[list[str]]:
        yield ["cargo", "build", "--target-dir", COMPILED.as_posix(), "--manifest-path", entrypoint.as_posix(), "-r"]

    def run_command(self, entrypoint: Path, base_path: Path) -> list[str]:
        toml = tomllib.loads(base_path.joinpath(entrypoint).read_text())
        name = toml["package"]["name"]
        return [COMPILED.joinpath("release").joinpath(name).as_posix()]


@dataclass
class TMSimulator:
    language: Language
    root_folder: Path
    files: list[Path]
    entrypoint: Path

    @classmethod
    def gather_files(cls, path: Path, depth: int | None) -> Iterable[Path]:
        for file in path.iterdir():
            if file.is_file() and Language.identify(file):
                yield file
            elif file.is_dir() and not file.name.startswith(".") and file.name != "__MACOSX":
                yield from cls.gather_files(file, depth and depth - 1)

    @classmethod
    def discover(cls, path: Path, depth: int | None = None) -> Self | list[Path]:
        files = [file.relative_to(path) for file in cls.gather_files(path, depth)]
        with contextlib.suppress(StopIteration):
            entrypoints = [(f, Language.identify(f, "projectfile")) for f in files]
            entrypoint, lang = next((f, lang) for f, lang in entrypoints if lang)
            return cls(lang, path, files, entrypoint)

        for test in ("", "main", "sim", "program"):
            match [f for f in files if f.stem.lower().find(test) != -1]:
                case []:
                    pass
                case [entrypoint]:
                    return cls(Language._registry[entrypoint.suffix], path, files, entrypoint)
                case _ if test != "":
                    return files
                case _:
                    pass
        return files

    def build(self, client: DockerClient, tms_folder: Path) -> BuiltSimulator:
        lang = self.language
        source_mount = Mount(CODE.as_posix(), str(self.root_folder.absolute()), type="bind", read_only=False)
        tms_mount = Mount(TMS.as_posix(), str(tms_folder.absolute()), type="bind", read_only=True)
        container = client.containers.run(
            lang.docker_image,
            command="bash",
            mounts=[source_mount, tms_mount],
            tty=True,
            detach=True,
        )
        container.exec_run(f"mkdir {COMPILED.as_posix()}")
        for command in lang.build_commands(self.files, self.entrypoint):
            exit_code, output = container.exec_run(command, workdir=CODE.as_posix())
            if exit_code:
                raise RuntimeError(output.decode("utf-8"))
        return BuiltSimulator(self.language, self.root_folder, self.files, self.entrypoint, container)


def collect(stream: Iterable[tuple[bytes, bytes]]) -> tuple[str, str]:
    out, err = [], []
    for out_chunk, err_chunk in stream:
        if out_chunk:
            out.append(out_chunk)
        if err_chunk:
            err.append(err_chunk)
    return b"".join(out[:1000]).decode(), b"".join(err).decode()


@dataclass
class BuiltSimulator(TMSimulator):
    container: DockerContainer

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.container.remove(force=True)

    def run(self, tm_name: str, input: str) -> str:
        command = [*self.language.run_command(self.entrypoint, self.root_folder), f"{tm_name}.TM", input]
        _, gen = self.container.exec_run(command, workdir=TMS.as_posix(), demux=True, stream=True)
        with ThreadPoolExecutor() as exec:
            future = exec.submit(collect, gen)
            try:
                out, err = future.result(5)
            except TimeoutError as e:
                pid_out: str = self.container.exec_run("ps").output.decode()
                pid = pid_out.splitlines()[1].split()[0].strip()
                self.container.exec_run(["kill", "-9", pid])
                raise TimeoutError(future.result()[0]) from e
        if err:
            raise ValueError(err)
        else:
            return out
