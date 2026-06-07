import json
import os
import socket
import time
from typing import Any

from .models import Breakpoint, DebugSession, Scope, SessionInfo, StackFrame, Variable
from .state import DebugState, clear_state, save_state

SOCKET_PATH = os.path.expanduser("~/.crickit/bridge.sock")

_id_counter = 0


def _next_id() -> int:
    global _id_counter
    _id_counter += 1
    return _id_counter


def _read_message(sock: socket.socket) -> dict[str, Any]:
    """Read one Content-Length-framed JSON-RPC message from the socket."""
    raw = b""
    while b"\r\n\r\n" not in raw:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("Bridge closed connection")
        raw += chunk

    header_part, rest = raw.split(b"\r\n\r\n", 1)
    content_length = 0
    for line in header_part.decode().splitlines():
        if line.lower().startswith("content-length:"):
            content_length = int(line.split(":", 1)[1].strip())

    while len(rest) < content_length:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("Bridge closed connection mid-message")
        rest += chunk

    return json.loads(rest[:content_length])


def _send_request(sock: socket.socket, method: str, params: Any = None) -> Any:
    """Send a JSON-RPC 2.0 request and return the result, draining any notifications first."""
    req_id = _next_id()
    request: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        request["params"] = params

    body = json.dumps(request).encode()
    header = f"Content-Length: {len(body)}\r\n\r\n".encode()
    sock.sendall(header + body)

    while True:
        msg = _read_message(sock)
        if "id" in msg:
            # It's the response to our request
            if "error" in msg:
                raise RuntimeError(f"RPC error: {msg['error']}")
            return msg.get("result")
        # Notification — discard (caller uses _send_and_wait_for_stop for blocking commands)


class SessionTerminatedError(Exception):
    pass


def _send_and_wait_for_stop(
    sock: socket.socket,
    method: str,
    params: Any = None,
    timeout: float = 30.0,
) -> DebugState:
    """Send a stepping request and block until debug/stopped arrives, then save state."""
    req_id = _next_id()
    request: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        request["params"] = params

    body = json.dumps(request).encode()
    header = f"Content-Length: {len(body)}\r\n\r\n".encode()
    sock.sendall(header + body)

    sock.settimeout(timeout)
    deadline = time.monotonic() + timeout

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for debug/stopped after {timeout}s")
        sock.settimeout(remaining)
        msg = _read_message(sock)

        method_in = msg.get("method", "")

        if method_in == "debug/stopped":
            p = msg.get("params", {})
            session_id = p.get("sessionId", "")
            thread_id = p.get("threadId", 1)
            reason = p.get("reason", "")
            description = p.get("description", "")
            # Fetch the top frame to get stopped_at location
            stopped_at = description or reason
            state = DebugState(
                session_id=session_id,
                thread_id=thread_id,
                frame_id=0,
                reason=reason,
                stopped_at=stopped_at,
            )
            save_state(state)
            return state

        if method_in == "debug/terminated":
            clear_state()
            raise SessionTerminatedError("Debug session terminated")

        # Ignore other notifications and the response to our request


def connect(timeout: float = 3.0) -> socket.socket:
    if not os.path.exists(SOCKET_PATH):
        raise FileNotFoundError(SOCKET_PATH)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(SOCKET_PATH)
    return sock


def get_debug_sessions() -> list[DebugSession]:
    sock = connect()
    try:
        result = _send_request(sock, "debug/sessions")
        return [DebugSession(**s) for s in (result or [])]
    finally:
        sock.close()


def launch_debug_session(
    program: str,
    *,
    debug_type: str | None = None,
    args: list[str] | None = None,
    stop_on_entry: bool = False,
) -> SessionInfo:
    params: dict[str, Any] = {"program": program}
    if debug_type is not None:
        params["type"] = debug_type
    if args:
        params["args"] = args
    if stop_on_entry:
        params["stopOnEntry"] = True

    sock = connect(timeout=15.0)
    try:
        if stop_on_entry:
            return _launch_and_wait_for_stop(sock, params)
        result = _send_request(sock, "debug/launch", params)
        return SessionInfo(**result)
    finally:
        sock.close()


def _launch_and_wait_for_stop(
    sock: socket.socket,
    params: Any,
    timeout: float = 30.0,
) -> SessionInfo:
    """Launch and block until both the launch response and the entry debug/stopped arrive, saving state."""
    req_id = _next_id()
    request: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": "debug/launch", "params": params}

    body = json.dumps(request).encode()
    header = f"Content-Length: {len(body)}\r\n\r\n".encode()
    sock.sendall(header + body)

    sock.settimeout(timeout)
    deadline = time.monotonic() + timeout

    session_info: SessionInfo | None = None
    stopped = False

    while session_info is None or not stopped:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for debug/stopped after {timeout}s")
        sock.settimeout(remaining)
        msg = _read_message(sock)

        if msg.get("id") == req_id:
            if "error" in msg:
                raise RuntimeError(f"RPC error: {msg['error']}")
            session_info = SessionInfo(**msg["result"])
            continue

        method_in = msg.get("method", "")

        if method_in == "debug/stopped":
            p = msg.get("params", {})
            reason = p.get("reason", "")
            description = p.get("description", "")
            state = DebugState(
                session_id=p.get("sessionId", ""),
                thread_id=p.get("threadId", 1),
                frame_id=0,
                reason=reason,
                stopped_at=description or reason,
            )
            save_state(state)
            stopped = True
        elif method_in == "debug/terminated":
            clear_state()
            raise SessionTerminatedError("Debug session terminated")

    return session_info


def set_breakpoint(file: str, line: int, condition: str | None = None) -> Breakpoint:
    params: dict[str, Any] = {"file": file, "line": line}
    if condition is not None:
        params["condition"] = condition
    sock = connect()
    try:
        result = _send_request(sock, "debug/setBreakpoint", params)
        return Breakpoint(**result)
    finally:
        sock.close()


def remove_breakpoint(bp_id: str) -> None:
    sock = connect()
    try:
        _send_request(sock, "debug/removeBreakpoint", {"id": bp_id})
    finally:
        sock.close()


def list_breakpoints() -> list[Breakpoint]:
    sock = connect()
    try:
        result = _send_request(sock, "debug/listBreakpoints")
        return [Breakpoint(**b) for b in (result or [])]
    finally:
        sock.close()


def _step_command(method: str) -> DebugState:
    from .state import load_state

    state = load_state()
    sock = connect(timeout=35.0)
    try:
        return _send_and_wait_for_stop(
            sock,
            method,
            {"sessionId": state.session_id, "threadId": state.thread_id},
        )
    finally:
        sock.close()


def continue_session() -> DebugState:
    return _step_command("debug/continue")


def step_over() -> DebugState:
    return _step_command("debug/next")


def step_into() -> DebugState:
    return _step_command("debug/stepIn")


def step_out() -> DebugState:
    return _step_command("debug/stepOut")


def get_stack_trace() -> list[StackFrame]:
    from .state import load_state

    state = load_state()
    sock = connect()
    try:
        result = _send_request(
            sock,
            "debug/stackTrace",
            {"sessionId": state.session_id, "threadId": state.thread_id},
        )
        return [StackFrame(**f) for f in (result or [])]
    finally:
        sock.close()


def get_scopes(frame_id: int) -> list[Scope]:
    from .state import load_state

    state = load_state()
    sock = connect()
    try:
        result = _send_request(
            sock,
            "debug/scopes",
            {"sessionId": state.session_id, "frameId": frame_id},
        )
        return [
            Scope(
                name=s["name"],
                variables_reference=s["variablesReference"],
                expensive=s["expensive"],
            )
            for s in (result or [])
        ]
    finally:
        sock.close()


def get_variables(variables_reference: int) -> list[Variable]:
    from .state import load_state

    state = load_state()
    sock = connect()
    try:
        result = _send_request(
            sock,
            "debug/variables",
            {"sessionId": state.session_id, "variablesReference": variables_reference},
        )
        return [
            Variable(
                name=v["name"],
                value=v["value"],
                type=v["type"],
                variables_reference=v["variablesReference"],
            )
            for v in (result or [])
        ]
    finally:
        sock.close()
