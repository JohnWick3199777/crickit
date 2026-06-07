import json
import os
from dataclasses import asdict, dataclass

STATE_PATH = os.path.expanduser("~/.crickit/state.json")


@dataclass
class DebugState:
    session_id: str
    thread_id: int
    frame_id: int
    reason: str
    stopped_at: str  # "file:line" for display


def save_state(state: DebugState) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(asdict(state), f)


def load_state() -> DebugState:
    if not os.path.exists(STATE_PATH):
        raise FileNotFoundError("No debug state — is the session stopped at a breakpoint?")
    with open(STATE_PATH) as f:
        data = json.load(f)
    return DebugState(**data)


def clear_state() -> None:
    if os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)
