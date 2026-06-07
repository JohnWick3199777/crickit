from dataclasses import dataclass


@dataclass
class DebugSession:
    id: str
    name: str
    type: str


@dataclass
class SessionInfo:
    id: str
    name: str
    type: str


@dataclass
class Breakpoint:
    id: str
    file: str
    line: int
    verified: bool


@dataclass
class StackFrame:
    id: int
    name: str
    source: str
    line: int
    column: int


@dataclass
class Scope:
    name: str
    variables_reference: int
    expensive: bool


@dataclass
class Variable:
    name: str
    value: str
    type: str
    variables_reference: int
