# Handoff: Crickit v0.2 — Breakpoints, Stack Traces, Variables

Read `crickit.md` for architecture and RPC contract. Read `handoff.md` for v0.1 context (what's already built).

The goal of this slice: be able to fully debug `examples/buggy.py` from the CLI — set breakpoints, launch, step through stops, inspect the call stack and local variables at each pause.

---

## What's already built (v0.1)

- VSCode extension: starts a JSON-RPC 2.0 server on `~/.crickit/bridge.sock`
- `debug/sessions` — list active sessions
- `debug/launch` — launch a program, returns when session starts
- `crickit sessions`, `crickit launch` CLI commands

**What's missing:** the bridge can't push events yet, and there are no handlers for breakpoints, continue, stack, or variables.

---

## What to build

### The core problem: notifications

`continue`, `step`, etc. are fire-and-forget from the Python side — execution resumes and the program runs until the next stop. The bridge needs to push a `debug/stopped` notification when that happens, and the Python client needs to receive it on the same connection before returning.

**Design: keep the socket open for the duration of a blocking command.** After sending `debug/continue`, the Python client reads messages off the socket until a `debug/stopped` notification arrives, then closes the socket and saves state.

**State file: `~/.crickit/state.json`** — written after every stop, read by stateless commands (`stack`, `vars`).

```json
{
  "sessionId": "abc-123",
  "threadId": 1,
  "frameId": 0,
  "reason": "breakpoint",
  "stoppedAt": "buggy.py:5"
}
```

---

### 1. VSCode Extension — add to `server.ts` + `extension.ts`

#### a. `DebugAdapterTracker` — push notifications to connected clients

Register a `DebugAdapterTrackerFactory` in `extension.ts`:

```typescript
context.subscriptions.push(
  vscode.debug.registerDebugAdapterTrackerFactory('*', server.trackerFactory())
);
```

In `server.ts`, add a `trackerFactory()` method that returns a factory. The tracker watches DAP messages from the adapter and broadcasts JSON-RPC notifications to all connected clients when it sees `stopped`, `terminated`, `continued`, or `output` events:

```typescript
// message is a raw DAP protocol message
onDidSendMessage(message: any): void {
  if (message.type !== 'event') return;
  switch (message.event) {
    case 'stopped':
      self.broadcast('debug/stopped', {
        sessionId: session.id,
        threadId: message.body.threadId,
        reason: message.body.reason,
        description: message.body.description,
      });
      break;
    case 'terminated':
      self.broadcast('debug/terminated', { sessionId: session.id });
      break;
    case 'continued':
      self.broadcast('debug/continued', { sessionId: session.id, threadId: message.body.threadId });
      break;
    case 'output':
      self.broadcast('debug/output', {
        sessionId: session.id,
        category: message.body.category,
        output: message.body.output,
      });
      break;
  }
}
```

Add a `broadcast(method, params)` method to `CrickitServer` that sends a JSON-RPC notification (no `id` field) to all active connections using `conn.sendNotification(method, params)`.

#### b. New RPC request handlers — add inside the `net.createServer` callback

All DAP calls go through `session.customRequest(dapMethod, params)` which returns a Promise.

```
debug/setBreakpoint   { file, line, condition? }   → { id, file, line, verified }
debug/removeBreakpoint  { id }                     → void
debug/listBreakpoints   (no params)                → [{ id, file, line, verified }]
debug/continue          { sessionId, threadId }    → void
debug/next              { sessionId, threadId }    → void
debug/stepIn            { sessionId, threadId }    → void
debug/stepOut           { sessionId, threadId }    → void
debug/stackTrace        { sessionId, threadId }    → [{ id, name, source, line, column }]
debug/scopes            { sessionId, frameId }     → [{ name, variablesReference, expensive }]
debug/variables         { sessionId, variablesReference } → [{ name, value, type, variablesReference }]
```

For breakpoints, use the VSCode API directly (not `customRequest`):
- `vscode.debug.addBreakpoints([new vscode.SourceBreakpoint(new vscode.Location(uri, pos))])`
- `vscode.debug.removeBreakpoints([bp])`
- `vscode.debug.breakpoints` — the current list

For stack/scopes/variables, use `session.customRequest`:
```typescript
const result = await session.customRequest('stackTrace', { threadId, startFrame: 0, levels: 20 });
return result.stackFrames;
```

For continue/step:
```typescript
await session.customRequest('continue', { threadId });
// return void — the stopped notification will come separately via the tracker
```

---

### 2. Python Core — `client.py` + `models.py`

#### New models (`models.py`)

```python
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
    variables_reference: int  # > 0 means it has children (expandable)
```

#### State file (`state.py`, new file)

```python
STATE_PATH = os.path.expanduser("~/.crickit/state.json")

@dataclass
class DebugState:
    session_id: str
    thread_id: int
    frame_id: int
    reason: str
    stopped_at: str  # "file:line" for display

def save_state(state: DebugState) -> None: ...
def load_state() -> DebugState: ...  # raises FileNotFoundError if not stopped
def clear_state() -> None: ...
```

#### Updated `_send_request` — drain notifications before the response

The response to a request might arrive after one or more notifications (e.g. a `debug/output` notification arrives before the `debug/continue` response). Distinguish them: a response has an `"id"` field; a notification does not.

Add a `_read_message(sock)` helper that reads one framed message and returns the parsed dict.

Add a `_send_and_wait_for_stop(sock, method, params)` function that:
1. Sends the request
2. Reads messages in a loop:
   - If it's the response to our request → set aside
   - If it's a `debug/stopped` notification → save state, return
   - If it's `debug/terminated` → clear state, raise `SessionTerminatedError`
3. Timeout after 30 seconds

#### New client functions

```python
def set_breakpoint(file: str, line: int, condition: str | None = None) -> Breakpoint
def remove_breakpoint(bp_id: str) -> None
def list_breakpoints() -> list[Breakpoint]

def continue_session() -> DebugState      # blocks until debug/stopped
def step_over() -> DebugState             # blocks until debug/stopped
def step_into() -> DebugState             # blocks until debug/stopped
def step_out() -> DebugState              # blocks until debug/stopped

def get_stack_trace() -> list[StackFrame]    # uses state.session_id, state.thread_id
def get_scopes(frame_id: int) -> list[Scope]
def get_variables(variables_reference: int) -> list[Variable]
```

---

### 3. Python CLI — new commands in `main.py`

```
crickit bp add <file> <line> [--condition EXPR]   Set a breakpoint
crickit bp rm <id>                                Remove a breakpoint
crickit bp list                                   List all breakpoints

crickit continue                                  Continue until next stop
crickit step                                      Step over (next line)
crickit step-in                                   Step into a call
crickit step-out                                  Step out of current frame

crickit stack                                     Print the call stack at current stop
crickit vars [--frame FRAME_ID]                   Print local variables (default: top frame)
```

**`bp` is a Click group.** `add`, `rm`, `list` are subcommands.

**`continue` / `step` / `step-in` / `step-out`** print the stop reason and location after blocking:
```
Stopped  reason=breakpoint  buggy.py:5
```

**`stack`** prints a numbered table:
```
  #  Function              File       Line
  0  calculate_average     buggy.py      5   ← current frame
  1  process_data          buggy.py     12
  2  <module>              buggy.py     24
```

**`vars`** prints a two-column table of name → value for all non-expensive scopes in the current frame. Nested objects (variablesReference > 0) show their type and reference id for now — no recursive expansion yet.

---

## Repo changes summary

```
bridges/vscode/src/
  server.ts        ← add broadcast(), trackerFactory(), 10 new RPC handlers
  extension.ts     ← register tracker factory

python/core/src/crickit_core/
  models.py        ← add Breakpoint, StackFrame, Scope, Variable
  state.py         ← new: DebugState, save/load/clear
  client.py        ← update _send_request, add 10 new functions

python/cli/src/crickit_cli/
  main.py          ← add bp group, continue, step, step-in, step-out, stack, vars
```

---

## Acceptance criteria

Run this sequence against `examples/buggy.py` (the file has a `ZeroDivisionError` when `group_c = []` hits `total / len(numbers)`):

```bash
crickit launch examples/buggy.py --stop-on-entry
# Session started  buggy.py  type=debugpy  (stopped at line 1)

crickit bp add examples/buggy.py 5
# Breakpoint set  id=1  buggy.py:5  verified=True

crickit continue
# Stopped  reason=breakpoint  buggy.py:5

crickit stack
# 0  calculate_average  buggy.py:5    ← current
# 1  process_data       buggy.py:12
# 2  <module>           buggy.py:24

crickit vars
# numbers  [10, 20, 30, 40]
# total    0

crickit continue
# Stopped  reason=breakpoint  buggy.py:5   (group_b hit)

crickit continue
# Stopped  reason=breakpoint  buggy.py:5   (group_c hit — numbers=[])

crickit vars
# numbers  []
# total    0
# (next continue will raise ZeroDivisionError)
```

---

## Notes

- `session.customRequest` is async in TypeScript — all new handlers must be `async` and return Promises
- Breakpoint IDs: VSCode's `SourceBreakpoint` has no stable string ID at creation time; use the breakpoint's `id` property after `vscode.debug.breakpoints` is read back. Store a local map `file:line → bp object` so `debug/removeBreakpoint` and `debug/listBreakpoints` can look them up.
- `debug/stopped` from the tracker fires on the extension host thread — it's safe to call `conn.sendNotification` there
- Python target: 3.11+, use `|` union syntax
- The `frameId` stored in state should default to the top frame (index 0 from the stack trace). `crickit vars` uses it without requiring the user to specify it.
