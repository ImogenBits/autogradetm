import operator
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
TESTS = [(name, input, tm :=TM.get(name), tm(input, "configs")) for name, input in TEST_INPUTS]


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
                    *(f"{i}    {config:>}" for i, config in islice(enumerate(long), i)),
                ]
                if i != diff:
                    if i != 0:
                        res.append("...")
                    res.extend(f"{i + len(short)}    {config:>}" for i, config in enumerate(long[i - diff :]))
                return "\n".join(res)

    res = ["[header]The correct and actually outputted config sequences are:[/]", "step    correct    output"]
    for i, (good, bad) in enumerate(zip_longest(correct, err, fillvalue="")):
        if good == bad:
            continue
        res.append(f"{i}    {good:>}    {bad:>}")
    return "\n".join(res)


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

    submission_folders = sorted(
        (
            (f, int(f.name.split()[3].split("_")[0]))
            for f in assignment_submissions.iterdir()
            if f.is_dir() or f.suffix == ".zip"
        ),
        key=operator.itemgetter(1),
    )
    for submission, group in submission_folders:
        if group != submission_folders[0][1]:
            response = Confirm.ask(f"Do you want to continue with group {group}?", default="y")
            if not response:
                raise Abort

        console.print(f"[heading]Processing submission of group {group}")
        if submission.is_file():
            with ZipFile(submission) as zipped:
                tmp = assignment_submissions / "__tmp__"
                tmp.mkdir()
                zipped.extractall(tmp)
            submission.unlink()
            tmp.rename(submission.with_suffix(""))

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

        try:
            simulator = simulator.build(client, TM_FOLDER)
        except RuntimeError as e:
            console.print(f"[error]Error when building submission code:[/]\n{e.args[0]}")
            continue
        with simulator:
            for tm_name, input, tm, correct in TESTS:
                try:
                    res = simulator.run(tm_name, input)
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


@app.command()
def blep(): ...


if __name__ == "__main__":
    app()
