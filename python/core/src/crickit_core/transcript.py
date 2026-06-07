import json
import os
from datetime import datetime, timezone

RECORDING_PATH = os.path.expanduser("~/.crickit/recording.json")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def start(path: str) -> str:
    path = os.path.abspath(os.path.expanduser(path))
    os.makedirs(os.path.dirname(RECORDING_PATH), exist_ok=True)
    with open(RECORDING_PATH, "w") as f:
        json.dump({"path": path}, f)
    with open(path, "w") as f:
        json.dump({"startedAt": _now(), "steps": []}, f, indent=2)
    return path


def stop() -> str | None:
    path = active_path()
    if path is None:
        return None
    os.remove(RECORDING_PATH)
    return path


def active_path() -> str | None:
    if not os.path.exists(RECORDING_PATH):
        return None
    with open(RECORDING_PATH) as f:
        return json.load(f)["path"]


def record_step(command: str, result: dict | None) -> None:
    path = active_path()
    if path is None:
        return
    with open(path) as f:
        transcript = json.load(f)
    transcript["steps"].append({"command": command, "at": _now(), "result": result})
    with open(path, "w") as f:
        json.dump(transcript, f, indent=2)
