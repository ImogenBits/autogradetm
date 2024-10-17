from __future__ import annotations

from collections.abc import Container
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
class Project:
    language: Language
    root_folder: Path
    entrypoint: Path

    code: ClassVar[Path] = Path("/code/")
    compiled: ClassVar[Path] = Path("/compiled/")
    tms: ClassVar[Path] = Path("/TMs/")

    def build_command(self, source_file: Path) -> str | None:
        if self.language.build_command is None:
            return None
        return self._format_cmd(self.language.build_command) + f" {self.code / source_file}"

    def run_command(self, tm_filename: str, input: str) -> str:
        return  self._format_cmd(self.language.run_command) + f" {tm_filename}.TM {input}"

    def _format_cmd(self, base_command: str) -> str:
        return base_command.format(
            code=self.code,
            compiled=self.compiled,
            entrypoint=self.entrypoint,
            tms=self.tms,
        )

    @classmethod
    def discover(cls, path: Path, depth: int | None = None, names: Container[str] = (), root: Path | None = None) -> Self | None:
        root = root or path
        for element in path.iterdir():
            if element.is_file() and element.suffix in Language._registry and element.stem in names:
                return cls(Language._registry[element.suffix], root, element.relative_to(root))
            elif element.is_dir() and depth != 0:
                return cls.discover(element, depth and depth - 1, names, root)

    def build(self, client: DockerClient, tms_folder: Path) -> Program:
        lang = self.language
        source_mount = Mount(str(self.code), str(self.root_folder), type="bind", read_only=True)
        tms_mount = Mount(str(self.tms), str(tms_folder), type="bind", read_only=True)
        container = client.containers.create(lang.docker_image, detach=True, mounts=[source_mount, tms_mount])
        container.exec_run(f"mkdir {self.compiled}")
        if lang.build_command:
            for file in self.entrypoint.parent.iterdir():
                if file.suffix != lang.extension:
                    continue
                container.exec_run(self.build_command(file.relative_to(self.root_folder)))
        return Program(self.language, self.root_folder, self.entrypoint, container)


@dataclass
class Program(Project):
    container: DockerContainer

    def run(self, tm_file: str, input: str) -> str:
        res = self.container.exec_run(self.run_command(tm_file, input), workdir=self.tms)
        return cast(bytes, res.output).decode("utf-8")
