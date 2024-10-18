from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Self, cast

from docker import DockerClient
from docker.models.containers import Container as DockerContainer
from docker.types import Mount


@dataclass
class Language:
    name: str
    extension: str
    docker_image: str
    build_command: str | None
    run_command: str

    _registry: ClassVar[dict[str, Self]] = {}

    def __post_init__(self) -> None:
        self._registry[self.extension] = self


Language("Python", ".py", "python:3.13", None, "py {code}/{entrypoint}")
Language("Java", ".java", "maven:latest", "javac -d {compiled}", "java -cp {compiled} {entrypoint.stem}")


@dataclass
class TMSimulator:
    language: Language
    root_folder: Path
    files: list[Path]
    entrypoint: Path

    code: ClassVar[Path] = Path("/code/")
    compiled: ClassVar[Path] = Path("/compiled/")
    tms: ClassVar[Path] = Path("/TMs/")

    def build_command(self, source_file: Path) -> str | None:
        if self.language.build_command is None:
            return None
        return self._format_cmd(self.language.build_command) + f" {self.code / source_file}"

    def run_command(self, tm_filename: str, input: str) -> str:
        return self._format_cmd(self.language.run_command) + f" {tm_filename}.TM {input}"

    def _format_cmd(self, base_command: str) -> str:
        return base_command.format(
            code=self.code,
            compiled=self.compiled,
            entrypoint=self.entrypoint,
            tms=self.tms,
        )

    @classmethod
    def gather_files(cls, path: Path, depth: int | None) -> Iterable[Path]:
        for file in path.iterdir():
            if file.is_file() and file.suffix in Language._registry:
                yield file
            elif file.is_dir() and not file.name.startswith("."):
                yield from cls.gather_files(file, depth and depth - 1)

    @classmethod
    def discover(cls, path: Path, depth: int | None = None) -> Self | list[Path]:
        files = [file.relative_to(path) for file in cls.gather_files(path, depth)]
        for file in files:
            if file.stem.lower() == "main":
                return cls(Language._registry[file.suffix], path, files, file)
        return files

    def build(self, client: DockerClient, tms_folder: Path) -> BuiltSimulator:
        lang = self.language
        source_mount = Mount(str(self.code), str(self.root_folder), type="bind", read_only=True)
        tms_mount = Mount(str(self.tms), str(tms_folder), type="bind", read_only=True)
        container = client.containers.create(lang.docker_image, detach=True, mounts=[source_mount, tms_mount])
        container.exec_run(f"mkdir {self.compiled}")
        if lang.build_command:
            for file in self.files:
                container.exec_run(self.build_command(file.relative_to(self.root_folder)))
        return BuiltSimulator(self.language, self.root_folder, self.files, self.entrypoint, container)


@dataclass
class BuiltSimulator(TMSimulator):
    container: DockerContainer

    def run(self, tm_file: str, input: str) -> str:
        res = self.container.exec_run(self.run_command(tm_file, input), workdir=self.tms)
        return cast(bytes, res.output).decode("utf-8")
