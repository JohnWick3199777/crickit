# Crickit

A debugger CLI that drives any debugger GUI via a typed RPC bridge. An AI agent can control it by invoking CLI commands directly — the CLI is the interface for both humans and agents.

---

## Concept

The RPC contract is the stable interface. A **bridge** is any process that implements it. The Python core never knows or cares which bridge is running — it just connects to the socket and speaks the protocol. VSCode is the first bridge implementation; a custom GUI or headless DAP bridge are future possibilities.

---

## Tech Stack

| Layer | Language / Runtime | Key Libraries |
|---|---|---|
| CLI | Python + `uv` | `click`, `rich` |
| Core (RPC client) | Python + `uv` | `jsonrpc` |
| Shared types | Python + `uv` | `pydantic` |
| Bridge interface | — | JSON-RPC 2.0 over Unix socket (stable contract) |
| Bridge: VSCode | TypeScript | `vscode-jsonrpc`, `vscode.debug` API |
| Bridge: future (custom GUI, headless) | Any | Must implement the same RPC contract |

---

## Repository Layout

```
crickit/
├── python/                        # uv workspace
│   ├── pyproject.toml             # workspace root
│   ├── cli/                       # crickit CLI commands
│   │   └── src/crickit_cli/
│   ├── core/                      # RPC client, session model
│   │   └── src/crickit_core/
│   └── shared/                    # pydantic models, RPC method names
│       └── src/crickit_shared/
│
├── bridges/
│   ├── vscode/                    # Bridge v1: VSCode extension (TypeScript)
│   │   ├── src/
│   │   │   ├── extension.ts       # activate() — starts RPC server
│   │   │   ├── server.ts          # JSON-RPC server over Unix socket
│   │   │   ├── router.ts          # RPC method → vscode.debug API calls
│   │   │   └── tracker.ts         # DebugAdapterTracker → push notifications
│   │   └── package.json
│   │
│   └── <future>/                  # Bridge v2+: custom GUI, web UI, headless DAP
│       └── ...                    # Must implement the same RPC contract
│
├── schema/                        # language-agnostic RPC contract (source of truth)
│   ├── methods.ts                 # TypeScript types
│   └── methods.py                 # Python equivalents (hand-synced for now)
│
└── crickit.md
```

---

## Architecture

```
[ AI Agent / Human ]
    │
    ▼ invokes CLI commands
crickit CLI (Python)
    │
    ▼ calls
crickit Core (Python)
  - RPC client (Unix socket)
  - Session state
    │
    │  JSON-RPC 2.0 over Unix socket     ← stable contract, never changes
    │  (~/.crickit/bridge.sock)
    │
    ▼
[ Bridge ]  ← swappable implementation
    │
    ├── bridges/vscode/   (current)
    │     - JSON-RPC server
    │     - vscode.debug API calls
    │     - DebugAdapterTracker → push notifications
    │
    └── bridges/<future>/
          - JSON-RPC server
          - Own debug infrastructure
```

---

## Responsibility Boundaries

**Any Bridge**
- Owns the JSON-RPC server (Unix socket listener)
- Translates RPC requests into whatever debug infrastructure it wraps
- Pushes notifications back to Core when debug events occur
- No business logic — pure adapter

**Bridge: VSCode (TypeScript)**
- Delegates to `vscode.debug.*`
- Uses `DebugAdapterTracker` to observe all DAP traffic
- Gets VSCode's full UI (call stack, variables, breakpoints panels) for free

**Core (Python)**
- JSON-RPC client
- Session state (active sessions, thread IDs, current frame)
- Event loop reacting to `debug/stopped`

**CLI (Python)**
- `click` commands
- Delegates everything to Core
- `rich` output formatting — structured enough for an agent to parse

---

## RPC Contract

### Requests (Python → Bridge)

| Method | Params | Returns |
|---|---|---|
| `debug/launch` | `LaunchParams` | `SessionInfo` |
| `debug/stop` | `{ sessionId }` | `void` |
| `debug/stackTrace` | `{ sessionId, threadId }` | `StackFrame[]` |
| `debug/scopes` | `{ sessionId, frameId }` | `Scope[]` |
| `debug/variables` | `{ sessionId, variablesReference }` | `Variable[]` |
| `debug/evaluate` | `{ sessionId, expression, frameId }` | `EvaluateResult` |
| `debug/setBreakpoint` | `{ file, line, condition? }` | `Breakpoint` |
| `debug/removeBreakpoint` | `{ id }` | `void` |
| `debug/listBreakpoints` | `void` | `Breakpoint[]` |
| `debug/continue` | `{ sessionId, threadId }` | `void` |
| `debug/next` | `{ sessionId, threadId }` | `void` |
| `debug/stepIn` | `{ sessionId, threadId }` | `void` |
| `debug/stepOut` | `{ sessionId, threadId }` | `void` |

### Notifications (Bridge → Python, server-push)

| Method | Payload |
|---|---|
| `debug/stopped` | `{ sessionId, threadId, reason, description? }` |
| `debug/continued` | `{ sessionId, threadId }` |
| `debug/terminated` | `{ sessionId }` |
| `debug/output` | `{ sessionId, category, output }` |
| `debug/breakpointHit` | `{ sessionId, breakpointId, threadId }` |

---

## CLI Commands

```
crickit launch <config>        Start a debug session from a launch.json config or inline args
crickit stop [sessionId]       Stop the active (or specified) session
crickit stack                  Print the current call stack
crickit vars [frameId]         Print variables in scope for a frame
crickit eval <expression>      Evaluate an expression in the current frame
crickit bp add <file> <line>   Set a breakpoint
crickit bp rm <id>             Remove a breakpoint
crickit bp list                List all breakpoints
crickit continue               Continue execution
crickit step                   Step over
crickit step in                Step into
crickit step out               Step out
```
