from dataclasses import dataclass
from enum import IntEnum
from itertools import count, repeat, takewhile
from pathlib import Path
from typing import Self


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
class Tape:
    blank: str
    _left: list[str]
    _right: list[str]

    def __init__(self, blank_symbol: str, input: str) -> None:
        self.blank = blank_symbol
        self._left = []
        self._right = list(input)

    def __getitem__(self, pos: int, /) -> str:
        try:
            if pos < 0:
                return self._left[-pos - 1]
            else:
                return self._right[pos]
        except IndexError:
            return self.blank

    def __setitem__(self, pos: int, symbol: str, /) -> None:
        if pos < -len(self._left):
            self._left.extend(repeat(self.blank, -pos - len(self._left)))
        elif pos >= len(self._right):
            self._right.extend(repeat(self.blank, pos + 1 - len(self._right)))
        if pos < 0:
            self._left[-pos - 1] = symbol
        else:
            self._right[pos] = symbol


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
    def from_file(cls, file: Path) -> Self:
        num_states, input_alphabet, tape_alphabet, start, end, *trans_graph = file.read_text().splitlines()
        trans: dict[tuple[int, str], tuple[int, str, Direction]] = {}
        for line in trans_graph:
            if line.startswith(("#", "/")) or not line:
                continue
            state, symbol, out_state, out_symbol, dir, *_ = line.split(" ")
            trans[(int(state), symbol)] = (int(out_state), out_symbol, Direction.parse(dir))
        return cls(
            num_states=int(num_states),
            trans=trans,
            input_alphabet=set(input_alphabet),
            tape_alphabet=set(tape_alphabet),
            start=int(start),
            end=int(end),
        )

    def __call__(self, input: str) -> str:
        assert all(a not in self.input_alphabet for a in input)
        tape = Tape("B", input)
        state = self.start
        position = 0
        step = 0
        while state != self.end:
            state, tape[position], move = self.trans[(state, tape[position])]
            position += move
            step += 1
            if step >= 1_000_000:
                raise RuntimeError
        return "".join(takewhile(self.input_alphabet.__contains__, map(tape.__getitem__, count(position))))
