import json
import os
import socket
from typing import Any

from .models import DebugSession, SessionInfo

SOCKET_PATH = os.path.expanduser("~/.crickit/bridge.sock")

_id_counter = 0


def _next_id() -> int:
    global _id_counter
    _id_counter += 1
    return _id_counter


def _send_request(sock: socket.socket, method: str, params: Any = None) -> Any:
    """Send a JSON-RPC 2.0 request and return the result."""
    request: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": method,
    }
    if params is not None:
        request["params"] = params

    # vscode-jsonrpc uses Content-Length framing (same as LSP)
    body = json.dumps(request).encode()
    header = f"Content-Length: {len(body)}\r\n\r\n".encode()
    sock.sendall(header + body)

    # Read response with Content-Length framing
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
            raise ConnectionError("Bridge closed connection mid-response")
        rest += chunk

    response = json.loads(rest[:content_length])
    if "error" in response:
        raise RuntimeError(f"RPC error: {response['error']}")
    return response.get("result")


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

    # launch can take a few seconds for VSCode to start the session
    sock = connect(timeout=15.0)
    try:
        result = _send_request(sock, "debug/launch", params)
        return SessionInfo(**result)
    finally:
        sock.close()
