from pathlib import Path
from typing import Annotated
from zipfile import ZipFile

from docker import from_env
from docker.errors import APIError, DockerException
from rich.console import Console
from rich.prompt import Prompt
from rich.theme import Theme
from typer import Abort, Argument, Typer

from autogradetm.simulators import Language, TMSimulator
from autogradetm.turing_machine import TM, Configuration

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

TM_FOLDER = Path(__file__).parent / "tms"
TESTS = [
    ("add", "0#0"),
    ("add", "11#00111"),
    ("equal", "11000#001"),
    ("equal", "11000#101"),
    ("invert", "0101"),
    ("invert", "111"),
]


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

    for submission in assignment_submissions.iterdir():
        if submission.is_file() and submission.suffix != ".zip":
            continue
        group = int(submission.name.split()[3].split("_")[0])
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

        with simulator.build(client, TM_FOLDER) as simulator:
            for tm_name, input in TESTS:
                tm = TM.from_spec(TM_FOLDER.joinpath(f"{tm_name}.TM").read_text())
                correct = tm(input, "configs")
                res = simulator.run(tm_name, input)
                res = [Configuration.parse(line, tm.input_alphabet) for line in res.splitlines()]
                if res == correct:
                    console.print(f"[success]Correctly simulated TM '{tm_name}' on input '{input}'.")
                else:
                    console.print(
                        f"[error]Incorrectly simulated TM '{tm_name}' on input '{input}'.[/]\n"
                        f"Correct output:\n{"\n".join(f"{c}\n" for c in correct)}\n"
                        f"Simulation result:\n{"\n".join(f"{c}\n" for c in res)}\n"
                    )


@app.command()
def blep(): ...


if __name__ == "__main__":
    app()
