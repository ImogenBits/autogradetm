from collections.abc import Container, Iterable
from dataclasses import dataclass
from enum import IntEnum
from itertools import chain, islice, takewhile
from pathlib import Path
from typing import ClassVar, Literal, Self, overload

TM_FOLDER = Path(__file__).parent / "tms"


class Direction(IntEnum):
    L = -1
    N = 0
    R = 1

    @classmethod
    def parse(cls, val: str) -> Self:
        match val:
            case "L" | "N" | "R":
                return getattr(cls, val)
            case _:
                raise ValueError


@dataclass
class Configuration:
    state: int
    left: str
    right: str

    def __post_init__(self) -> None:
        self.left = self.left.lstrip("B")
        self.right = self.right.rstrip("B")

    def __str__(self) -> str:
        return f"...{self.left}[{self.state}]{self.right}..."

    def __format__(self, format: str) -> str:
        if not format:
            return str(self)
        elif format == ">":
            return self.pretty()
        else:
            raise ValueError

    def pretty(self) -> str:
        left = ["[grey58]B[/]" if char == "B" else char for char in self.left]
        state = f"[cyan]\\[{self.state}][/]"
        right = ["[grey58]B[/]" if char == "B" else char for char in self.right]
        return f"...[grey58]B[/]{"".join(left)}{state}{"".join(right)}[grey58]B[/]..."

    @classmethod
    def parse(cls, data: str, alphabet: Container[str]) -> Self:
        left, right, num = [], [], []
        curr = left
        for char in data:
            if (curr is num and char.isdigit()) or char in alphabet:
                curr.append(char)
            elif char in " ." or (curr is num and char == "q"):
                continue
            elif char in "[|({":
                curr = num
            elif char in "]|)}":
                curr = right
            else:
                raise ValueError(f"Unexpected character {char} in TM configuration")
        return cls(int("".join(num)), "".join(left), "".join(right))


@dataclass
class Tape:
    _left: list[str]
    _right: list[str]
    _pos: int

    def __init__(self, input: str) -> None:
        self._left = []
        self._right = list(input) if input else ["B"]
        self._pos = 0

    def read(self) -> str:
        if self._pos < 0:
            return self._left[-self._pos - 1]
        else:
            return self._right[self._pos]

    def write(self, symbol: str) -> None:
        if self._pos < 0:
            self._left[-self._pos - 1] = symbol
        else:
            self._right[self._pos] = symbol

    def move(self, direction: Direction) -> None:
        self._pos += direction
        if self._pos < -len(self._left):
            self._left.append("B")
        elif self._pos >= len(self._right):
            self._right.append("B")

    def configuration(self, state: int) -> Configuration:
        left = reversed(self._left)
        right = iter(self._right)
        left_of_head = "".join(
            chain(islice(left, len(self._left) + min(self._pos, 0)), islice(right, max(self._pos, 0))),
        )
        right_of_head = "".join(chain(left, right))
        return Configuration(
            state=state,
            left=left_of_head,
            right=right_of_head,
        )

    def read_right(self) -> Iterable[str]:
        return chain(
            (self._left[i] for i in range(-min(self._pos, 0) - 1, -1, -1)),
            (self._right[i] for i in range(max(self._pos, 0), len(self._right))),
        )


@dataclass
class TM:
    num_states: int
    trans: dict[tuple[int, str], tuple[int, str, Direction]]
    input_alphabet: set[str]
    tape_alphabet: set[str]
    start: int
    end: int

    _cache: ClassVar[dict[str, Self]] = {}

    def __post_init__(self) -> None:
        assert self.start <= self.num_states, f"Start state {self.start} bigger than total {self.num_states}."
        assert self.end <= self.num_states, f"End state {self.end} bigger than total {self.num_states}"
        assert "B" not in self.input_alphabet, f"Blank symbol in input alphabet {self.input_alphabet}"
        if not self.input_alphabet < self.tape_alphabet:
            self.tape_alphabet |= self.input_alphabet
        if "B" not in self.tape_alphabet:
            self.tape_alphabet.add("B")
        for (state, symbol), (tar, write, _) in self.trans.items():
            assert state != self.end, f"Transition '{(state, symbol)}' starts from the ending state"
            assert state <= self.num_states, f"Transition '{(state, symbol)}' starts from a nonexistent state"
            assert symbol in self.tape_alphabet, f"Transition '{(state, symbol)}' starts from a nonexistent symbol"
            assert tar <= self.num_states, f"Transition '{(state, symbol)}' goes to a nonexistent state {tar}"
            assert write in self.tape_alphabet, f"Transition '{(state, symbol)}' writes a nonexistent letter {write}"

    @classmethod
    def from_spec(cls, spec: str) -> Self:
        num_states, input_alphabet, tape_alphabet, start, end, *trans_graph = spec.splitlines()
        trans: dict[tuple[int, str], tuple[int, str, Direction]] = {}
        for line in trans_graph:
            if line.startswith(("#", "/")) or not line:
                continue
            state, symbol, out_state, out_symbol, dir, *_ = line.split(" ")
            trans[int(state), symbol] = (int(out_state), out_symbol, Direction.parse(dir))
        return cls(
            num_states=int(num_states),
            trans=trans,
            input_alphabet=set(input_alphabet),
            tape_alphabet=set(tape_alphabet),
            start=int(start),
            end=int(end),
        )

    @classmethod
    def get(cls, name: str) -> Self:
        if name not in cls._cache:
            cls._cache[name] = cls.from_spec(TM_FOLDER.joinpath(f"{name}.TM").read_text())
        return cls._cache[name]

    @overload
    def __call__(self, input: str, *, log_configs: Literal[False] = False) -> str: ...
    @overload
    def __call__(self, input: str, *, log_configs: Literal[True]) -> tuple[str, list[Configuration]]: ...

    def __call__(self, input: str, *, log_configs: bool = False) -> str | tuple[str, list[Configuration]]:
        tape = Tape(input)
        state = self.start
        step = 0
        configs = [tape.configuration(state)]
        while state != self.end:
            try:
                state, symbol, direction = self.trans[state, tape.read()]
            except KeyError as e:
                if log_configs:
                    raise KeyError(*e.args, configs) from e
                else:
                    raise
            tape.write(symbol)
            tape.move(direction)
            step += 1
            if step >= 1_000_000:
                if log_configs:
                    raise TimeoutError(configs)
                else:
                    raise TimeoutError
            if log_configs:
                configs.append(tape.configuration(state))
        res = "".join(takewhile(self.input_alphabet.__contains__, tape.read_right()))
        return (res, configs) if log_configs else res
