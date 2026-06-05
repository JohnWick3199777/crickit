# Handoff: Crickit v0.1

Build the minimal working slice of Crickit: a VSCode extension that exposes an RPC server, and a Python CLI with a single command that lists active debug sessions.

Read `crickit.md` first for full context on the architecture and design decisions.

---

## What to build

### 1. VSCode Extension (`bridges/vscode/`)

A VSCode extension that:
- On `activate()`, starts a JSON-RPC 2.0 server over a Unix socket at `~/.crickit/bridge.sock`
- Handles one request: `debug/sessions` → returns the list of currently active VSCode debug sessions (name, id, type)
- On `deactivate()`, closes the socket

Use `vscode-jsonrpc` for the RPC server. Use the `vscode.debug.sessions` API to get active sessions.

### 2. Python CLI (`python/`)

A `uv` workspace with two packages:

**`crickit-core`** — RPC client
- Connects to `~/.crickit/bridge.sock`
- Sends a `debug/sessions` request
- Returns the result as a Python dataclass

**`crickit-cli`** — CLI
- One command: `crickit sessions`
- Calls core, prints the session list with `rich`
- If the socket doesn't exist: print a clear error ("crickit bridge is not running — open VSCode with the crickit extension installed")

---

## Acceptance criteria

1. Start a debug session in VSCode (any language, any config)
2. Run `crickit sessions` in the terminal
3. See the active session printed: name, id, type

---

## Repo layout to create

```
crickit/
├── bridges/
│   └── vscode/
│       ├── src/
│       │   ├── extension.ts
│       │   └── server.ts
│       ├── package.json
│       └── tsconfig.json
├── python/
│   ├── pyproject.toml          # uv workspace
│   ├── core/
│   │   ├── pyproject.toml
│   │   └── src/crickit_core/
│   │       ├── __init__.py
│   │       ├── client.py       # RPC client + connect()
│   │       └── models.py       # DebugSession dataclass
│   └── cli/
│       ├── pyproject.toml
│       └── src/crickit_cli/
│           ├── __init__.py
│           └── main.py         # click app, `sessions` command
├── crickit.md
└── handoff.md
```

---

## Notes

- Socket path: `~/.crickit/bridge.sock` (create `~/.crickit/` if it doesn't exist)
- The extension should log to the VSCode output channel "Crickit" when the server starts/stops
- Python target: 3.11+, use `uv` for dependency management
- TypeScript target: ES2020, Node 18+
- Keep it minimal — no session state, no event loop, no notifications yet
