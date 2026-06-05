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
