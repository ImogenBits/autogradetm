import operator
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from itertools import islice, zip_longest
from pathlib import Path
from typing import Annotated
from zipfile import ZipFile

from docker import from_env
from docker.errors import APIError, DockerException
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.theme import Theme
from typer import Abort, Argument, Typer

from autogradetm.simulators import Language, TMSimulator
from autogradetm.turing_machine import TM, TM_FOLDER, Configuration

app = Typer(pretty_exceptions_show_locals=True)
theme = Theme({
    "success": "green",
    "warning": "orange3",
    "error": "red",
    "attention": "magenta2",
    "heading": "blue",
    "info": "dim cyan",
})
console = Console(theme=theme)

TEST_INPUTS = [
    ("add", "0#0"),
    ("add", "11#00111"),
    ("equal", "11000#001"),
    ("equal", "11000#101"),
    ("invert", "0101"),
    ("invert", "111"),
]
TESTS = [(name, input, tm := TM.get(name), tm(input, log_configs=True)[1]) for name, input in TEST_INPUTS]


def truncate(lines: list[str]) -> str:
    return "\n".join(lines[:22]) + ("\n  ⋮" if len(lines) > 22 else "")


def get_diff(correct: list[Configuration], err: list[Configuration]) -> str:
    if (diff := len(correct) - len(err)) != 0:
        if diff > 0:
            long, short = correct, err
            header = "[header]The output is missing the following configurations:[/]"
        else:
            long, short = err, correct
            header = "[header]The output incorrectly contains the following configurations:[/]"
        for i in range(diff + 1):
            if long[i : (i - diff) or None] == short:
                res = [
                    header,
                    "step    config",
                    *(f"{i: >3}    {config:>}" for i, config in islice(enumerate(long), i)),
                ]
                if i != diff:
                    if i != 0:
                        res.append("⋮")
                    res.extend(f"{i + len(short): >3}    {config:>}" for i, config in enumerate(long[i - diff :]))
                return truncate(res)

    res = ["[header]The correct and actually outputted config sequences are:[/]", "step    correct    output"]
    for i, (good, bad) in enumerate(zip_longest(correct, err, fillvalue=" " * 9)):
        if good == bad:
            continue
        res.append(f"{i: >3}    {good:>}    {bad:>}")
    return truncate(res)


@dataclass
class ProcessSubmissions:
    folder: Path

    def __iter__(self) -> Iterator[tuple[Path, int]]:
        sorted_submissions = sorted(
            (
                (f, int(f.name.split()[3].split("_")[0]))
                for f in self.folder.iterdir()
                if f.is_dir() or f.suffix == ".zip"
            ),
            key=operator.itemgetter(1),
        )
        for submission, group in sorted_submissions:
            if group != sorted_submissions[0][1]:
                response = Confirm.ask(f"Do you want to continue with group {group}?", default="y")
                if not response:
                    raise Abort

            console.print(f"[heading]Processing submission of group {group}")
            if submission.is_file():
                with ZipFile(submission) as zipped:
                    tmp = self.folder / "__tmp__"
                    tmp.mkdir()
                    zipped.extractall(tmp)
                submission.unlink()
                submission = submission.with_suffix("")
                tmp.rename(submission)

            yield submission, group


@app.command(name="simulators")
def test_simulators(
    assignment_submissions: Annotated[
        Path, Argument(help="Path to the folder containing every student's submissions.")
    ],
):
    try:
        client = from_env()
    except (DockerException, APIError) as e:
        console.print("[error]Could not connect to the Docker daemon. Make sure you have Docker installed and running.")
        console.print_exception()
        raise Abort from e

    for submission, group in ProcessSubmissions(assignment_submissions):
        simulator = TMSimulator.discover(submission)
        if not simulator:
            console.print(f"[error]Could not find any code files in {submission.name}[/].")
            continue
        if isinstance(simulator, list):
            entrypoint = Path(
                Prompt.ask(
                    "[error]Could not find a definitive main file.\n"
                    "[/]Please manually select which file is the entrypoint",
                    choices=[str(s) for s in simulator],
                    console=console,
                    show_choices=True,
                )
            )
            simulator = TMSimulator(Language._registry[entrypoint.suffix], submission, simulator, entrypoint)

        message_start = "B" if client.images.list(simulator.language.docker_image) else "Downloading and b"
        try:
            with console.status(
                f"[info]{message_start}uilding Docker image for {simulator.language.__class__.__name__}, "
                f"this might take a bit."
            ):
                simulator = simulator.build(client, TM_FOLDER)
        except RuntimeError as e:
            console.print("[error]Error when building submission code:[/]")
            console.print(e.args[0], highlight=False, markup=False)
            continue
        with simulator:
            for tm_name, input, tm, correct in TESTS:
                try:
                    res = simulator.run(tm_name, input)
                except TimeoutError as e:
                    console.print(f"[warning]Simulating TM '{tm_name}' on input '{input}' ran into a timeout.")
                    res = e.args[0]
                except ValueError as e:
                    console.print(
                        f"[error]An error occured when simulating TM '{tm_name}' on input '{input}':[/]\n"
                        f"{e.args[0]}"
                    )
                    continue

                parsed, incorrect_lines = list[Configuration](), list[str]()
                for line in res.splitlines():
                    try:
                        parsed.append(Configuration.parse(line, tm.tape_alphabet))
                    except ValueError:
                        incorrect_lines.append(line)
                if parsed == correct:
                    console.print(f"[success]Correctly simulated TM '{tm_name}' on input '{input}'.")
                    continue

                console.print(f"[error]Simulating TM '{tm_name}' on input '{input}' produced incorrect results:")
                if incorrect_lines:
                    console.print(
                        "The following lines could not be parsed as TM configs:\n" + "\n".join(incorrect_lines)
                    )
                if not parsed:
                    console.print("[error]The output does not contain any TM configurations.")
                else:
                    console.print(get_diff(correct, parsed), highlight=False)
        console.print(f"[success]Finished testing group {group}.")


def collect_tms(path: Path) -> Iterable[Path]:
    if path.is_file() and path.suffix == ".TM":
        yield path
    elif path.is_dir() and not path.name.startswith(".") and path.name != "__MACOSX":
        for child in path.iterdir():
            yield from collect_tms(child)


@dataclass
class Exercise[T]:
    number: int
    identifiers: list[str]
    data: list[str]
    correct: Callable[[str], T]
    parse: Callable[[str], T]


TM_EXERCISES = [
    Exercise(
        4,
        ["vier", "four", "log"],
        ["", "0", "10", "111", "010101"],
        lambda i: len(bin(max(0, int(i, 2) - 1))) if i else 0,
        lambda o: int(o, 2),
    ),
    Exercise(
        5,
        ["fünf", "fuenf", "five", "count", "zähl", "zaehl"],
        ["", "10", "001", "110100101111", "110101011001"],
        lambda i: int(2 * i.count("0") == i.count("1")),
        lambda o: int(o[0]),
    ),
]


def format_configs(configs: list[Configuration], truncate: int | None = 20) -> str:
    if truncate is not None:
        offset = max(0, len(configs) - truncate)
        configs = configs[-truncate:]
    else:
        offset = 0
    out = [
        "Configuration sequence:\n",
        "[header]step    configuration[/]\n",
        "  ⋮\n" if offset else "",
        *(f"{i: >3}    {c:>}\n" for i, c in enumerate(configs, offset)),
    ]
    return "".join(out)


@app.command()
def tms(
    assignment_submissions: Annotated[
        Path, Argument(help="Path to the folder containing every student's submissions.")
    ],
):
    for folder, _ in ProcessSubmissions(assignment_submissions):
        tm_files = [f.relative_to(folder) for f in (collect_tms(folder))]
        for exercise in TM_EXERCISES:
            console.print(f"[header]Exercise {exercise.number}:")
            match tm_files:
                case []:
                    console.print("[error]Could not find any TM files.")
                    continue
                case [tm_file]:
                    pass
                case _:
                    patterns = [str(exercise.number), *exercise.identifiers]
                    candidates = [f for f in tm_files if any(f.name.find(p) != -1 for p in patterns)]
                    if len(candidates) == 1:
                        tm_file = candidates[0]
                    else:
                        paths = candidates or tm_files
                        parents = {p.parent for p in paths}
                        if len(parents) == 1:
                            parent = next(iter(parents))
                            paths = [p.name for p in paths]
                        else:
                            parent = None
                            paths = [str(p) for p in paths]

                        ret = Prompt.ask(
                            "[warning]Could not uniquely identify a TM file for this exercise.[/]\n"
                            "Please select the correct file manually or skip this exercise",
                            choices=["Skip", *paths],
                            show_choices=True,
                            default="Skip",
                            console=console,
                        )
                        if ret == "Skip":
                            console.print("Skipping this exercise.")
                            continue
                        else:
                            tm_file = parent.joinpath(ret) if parent else Path(ret)
            console.print(f"Using TM file '{tm_file}'.")

            try:
                tm = TM.from_spec(folder.joinpath(tm_file).read_text())
            except (ValueError, AssertionError) as e:
                console.print(f"[error]The TM file is formatted incorrectly:[/]\n{e}")
                continue
            for input in exercise.data:
                console.print(f"[header]Testing TM on input '{input}':")
                try:
                    output, configs = tm(input, log_configs=True)
                except KeyError as e:
                    console.print(f"[error]The TM file is missing a needed transition: {e.args[0]}.")
                    console.print(format_configs(e.args[1]))
                    continue
                except TimeoutError as e:
                    console.print("[error]The TM is stuck in an infinite loop.")
                    console.print(format_configs(e.args[0]))
                    continue
                correct = exercise.correct(input)
                try:
                    parsed = exercise.parse(output)
                except ValueError:
                    console.print(f"[error]The TM produces invalid output '{output}'")
                    console.print(format_configs(configs))
                    continue
                if parsed == correct:
                    console.print("[success]The TM runs correctly.")
                else:
                    console.print(f"[error]The TM outputs '{output}' instead of '{correct}'.")
                    console.print(format_configs(configs))


if __name__ == "__main__":
    app()
