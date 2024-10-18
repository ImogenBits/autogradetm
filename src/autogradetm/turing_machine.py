from collections.abc import Container, Iterable
from dataclasses import dataclass
from enum import IntEnum
from itertools import chain, islice, takewhile
from typing import Literal, Self, overload


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

    @classmethod
    def parse(cls, data: str, alphabet: Container[str]) -> Self:
        left, right, num = [], [], []
        curr = left
        for char in data:
            if (curr is num and char.isdigit()) or char in alphabet:
                curr.append(char)
            elif char in " .":
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
        self._right = list(input)
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
            (self._right[i] for i in range(min(self._pos, 0))),
        )


@dataclass
class TM:
    num_states: int
    trans: dict[tuple[int, str], tuple[int, str, Direction]]
    input_alphabet: set[str]
    tape_alphabet: set[str]
    start: int
    end: int

    def __post_init__(self) -> None:
        assert 1 <= self.start <= self.num_states
        assert 1 <= self.end <= self.num_states
        assert self.input_alphabet < self.tape_alphabet
        assert "B" not in self.input_alphabet
        assert "B" in self.tape_alphabet
        assert all(
            state != self.end and 1 <= state <= self.num_states and symbol in self.tape_alphabet
            for state, symbol in self.trans
        )
        assert all(
            1 <= state <= self.num_states and symbol in self.tape_alphabet for state, symbol, _ in self.trans.values()
        )

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

    @overload
    def __call__(self, input: str, output: Literal["result"] = "result") -> str: ...
    @overload
    def __call__(self, input: str, output: Literal["configs"]) -> list[Configuration]: ...

    def __call__(self, input: str, output: Literal["result", "configs"] = "result") -> str | list[Configuration]:
        assert all(a not in self.input_alphabet for a in input)
        tape = Tape(input)
        state = self.start
        step = 0
        configs = []
        while state != self.end:
            state, symbol, direction = self.trans[state, tape.read()]
            tape.write(symbol)
            tape.move(direction)
            step += 1
            if step >= 1_000_000:
                raise RuntimeError
            if output == "configs":
                configs.append(tape.configuration(state))
        if output == "result":
            return "".join(takewhile(self.input_alphabet.__contains__, tape.read_right()))
        else:
            return configs
