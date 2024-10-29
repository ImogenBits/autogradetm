from __future__ import annotations

import operator
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import IntEnum
from typing import ClassVar, Literal, Self, cast, get_args

type Condition = Literal["=", "<", "<=", ">", ">="]
CONDITION_ALIASES = cast(
    dict[str, Condition],
    {
        "≤": "<=",
        "≥": ">=",
        "==": "=",
    }
    | {cond: cond for cond in get_args(Condition.__value__)},
)


type ArithmeticCommand = Literal["ADD", "SUB", "MULT", "DIV"]
type Command = Literal["LOAD", "STORE"] | ArithmeticCommand


@dataclass
class RegisterRef:
    reg: int


class AccessType(IntEnum):
    constant = 0
    register = 1
    indirect = 2


@dataclass
class RegisterStatement:
    access_type: AccessType
    command: Command
    arg: int

    all_commands: ClassVar[set[str]] = {p + c for p in ("", "C", "IND") for c in get_args(Command.__value__)}

    def __init__(self, command: str, arg: str) -> None:
        self.arg = int(arg)
        if command.startswith("C"):
            self.access_type = AccessType.constant
            command = command[1:]
        elif command.startswith("IND"):
            self.access_type = AccessType.indirect
            command = command[3:]
        else:
            self.access_type = AccessType.register

        if command in get_args(Command.__value__):
            self.command = command
        else:
            raise ValueError
        if self.access_type == AccessType.constant and self.command == "STORE":
            raise ValueError


@dataclass
class GotoStatement:
    goto: int


@dataclass
class IfStatement:
    lhs: int | RegisterRef
    condition: Condition
    rhs: int | RegisterRef
    goto: int


class EndStatement:
    pass


type Statement = RegisterStatement | GotoStatement | IfStatement | EndStatement


def parse_expr(expr: str) -> int | RegisterRef:
    return RegisterRef(int(expr.strip("C() "))) if expr[0] == "C" else int(expr)


def parse_statement(line: str, line_num: int) -> tuple[int, Statement] | None:
    try:
        label, command, *rest = line.split()
    except ValueError:
        return None
    if label[-1] == ":":
        label = label[:-1]
    if label.isdecimal():
        line_num = int(label)
    else:
        line_num = line_num
        command, *rest = label, command, *rest

    match command:
        case _ if command in RegisterStatement.all_commands:
            return line_num, RegisterStatement(command, rest[0])
        case "GOTO":
            return line_num, GotoStatement(int(rest[0]))
        case "IF":
            lhs, cmp, rhs, _, goto, *_ = rest
            return line_num, IfStatement(
                parse_expr(lhs),
                CONDITION_ALIASES[cmp],
                parse_expr(rhs),
                int(goto),
            )
        case "END":
            return line_num, EndStatement()
        case _:
            return None


class ProgramDefnError(Exception):
    pass


class IfLhsNotC0(ProgramDefnError):
    pass


class IfRhsNotConst(ProgramDefnError):
    pass


def resolve_expr(registers: Mapping[int, int], value: int, num_indirection: int) -> int:
    for _ in range(num_indirection):
        value = registers[value]
    return value


@dataclass
class RAM:
    code: tuple[Statement, ...]

    arithmetic: ClassVar[dict[ArithmeticCommand, Callable[[int, int], int]]] = {
        "ADD": operator.add,
        "SUB": lambda x, y: max(0, x - y),
        "MULT": operator.mul,
        "DIV": lambda x, y: x // y if y else 0,
    }
    comparisons: ClassVar[dict[Condition, Callable[[int, int], bool]]] = {
        "<": operator.lt,
        "<=": operator.le,
        "=": operator.eq,
        ">=": operator.ge,
        ">": operator.gt,
    }

    @classmethod
    def from_program(cls, program: str) -> tuple[Self, list[ProgramDefnError]]:
        code = {
            res[0]: (res[1], line) for i, line in enumerate(program.splitlines()) if (res := parse_statement(line, i))
        }
        errors = list[ProgramDefnError]()
        for statement, line in code.values():
            if isinstance(statement, IfStatement):
                if not isinstance(statement.lhs, int):
                    errors.append(IfLhsNotC0(line))
                if not isinstance(statement.rhs, RegisterRef):
                    errors.append(IfRhsNotConst(line))
        code.setdefault(0, (GotoStatement(1), ""))
        self = cls(tuple(code.get(i, (EndStatement(), ""))[0] for i in range(max(code))))
        return self, errors

    def run(self, *args: int) -> Mapping[int, int]:
        registers = defaultdict(lambda: 0)
        program_counter = 0
        iteration = 0

        while True:
            curr = self.code[program_counter]
            program_counter += 1
            iteration += 1
            if iteration >= 1_000_000:
                raise TimeoutError
            match curr:
                case RegisterStatement(AccessType.register, "STORE", arg):
                    registers[arg] = registers[0]
                case RegisterStatement(AccessType.indirect, "STORE", arg):
                    registers[registers[arg]] = registers[0]
                case RegisterStatement(access, "LOAD", arg):
                    registers[0] = resolve_expr(registers, arg, access)
                case RegisterStatement(access, ("ADD" | "SUB" | "MULT" | "DIV") as cmd, arg):
                    first = registers[0]
                    second = resolve_expr(registers, arg, access)
                    registers[0] = self.arithmetic[cmd](first, second)

                case IfStatement(lhs, cond, rhs, goto):
                    first = lhs if isinstance(lhs, int) else registers[lhs.reg]
                    second = rhs if isinstance(rhs, int) else registers[rhs.reg]
                    if self.comparisons[cond](first, second):
                        program_counter = goto

                case GotoStatement(goto):
                    program_counter = goto
                case EndStatement():
                    return registers
                case _:
                    raise ValueError
