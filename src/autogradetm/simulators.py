from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Self

from docker import DockerClient
from docker.models.containers import Container as DockerContainer
from docker.types import Mount

CODE = Path("/code/")
COMPILED = Path("/compiled/")
TMS = Path("/TMs/")


def get_unique[T](test: Callable[[T], bool], items: Iterable[T]) -> T | None:
    res = [i for i in items if test(i)]
    if len(res) == 1:
        return res[0]
    else:
        return None


class Language:
    extension: ClassVar[str]
    docker_image: ClassVar[str]

    _registry: ClassVar[dict[str, Self]] = {}

    def __init_subclass__(cls) -> None:
        cls._registry[cls.extension] = cls()

    def build_commands(self, sources: list[Path]) -> Iterable[list[str]]:
        return []

    @abstractmethod
    def run_command(self, entrypoint: Path) -> list[str]: ...


class Python(Language):
    extension = ".py"
    docker_image = "python:3.13"

    def run_command(self, entrypoint: Path) -> list[str]:
        return ["python", CODE.joinpath(entrypoint).as_posix()]


class Java(Language):
    extension = ".java"
    docker_image = "maven:latest"

    def build_commands(self, sources: list[Path]) -> Iterable[list[str]]:
        yield ["javac", "-d", COMPILED.as_posix(), *(source.as_posix() for source in sources)]

    def run_command(self, entrypoint: Path) -> list[str]:
        return ["java", "-cp", COMPILED.as_posix(), entrypoint.stem]


class C(Language):
    extension = ".c"
    docker_image = "gcc:latest"

    main_path = COMPILED.joinpath("main").as_posix()

    def build_commands(self, sources: list[Path]) -> Iterable[list[str]]:
        yield ["gcc", "-o", self.main_path, *(f.as_posix() for f in sources)]

    def run_command(self, entrypoint: Path) -> list[str]:
        return [self.main_path]


class CPP(C):
    extension = ".cpp"

    def build_commands(self, sources: list[Path]) -> Iterable[list[str]]:
        for _, *args in super().build_commands(sources):
            yield ["g++", *args]


@dataclass
class TMSimulator:
    language: Language
    root_folder: Path
    files: list[Path]
    entrypoint: Path

    @classmethod
    def gather_files(cls, path: Path, depth: int | None) -> Iterable[Path]:
        for file in path.iterdir():
            if file.is_file() and file.suffix in Language._registry:
                yield file
            elif file.is_dir() and not file.name.startswith(".") and file.name != "__MACOSX":
                yield from cls.gather_files(file, depth and depth - 1)

    @classmethod
    def discover(cls, path: Path, depth: int | None = None) -> Self | list[Path]:
        files = [file.relative_to(path) for file in cls.gather_files(path, depth)]
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
        source_mount = Mount(CODE.as_posix(), str(self.root_folder.absolute()), type="bind", read_only=True)
        tms_mount = Mount(TMS.as_posix(), str(tms_folder.absolute()), type="bind", read_only=True)
        container = client.containers.run(
            lang.docker_image,
            command="bash",
            mounts=[source_mount, tms_mount],
            tty=True,
            detach=True,
        )
        container.exec_run(f"mkdir {COMPILED.as_posix()}")
        for command in lang.build_commands(self.files):
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
        command = [*self.language.run_command(self.entrypoint), f"{tm_name}.TM", input]
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
