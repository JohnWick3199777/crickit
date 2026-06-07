---
description: Debug a Python program with crickit (launch, breakpoints, step, inspect)
argument-hint: <file> [line]
---

Debug `$1` using the `crickit` CLI, stopping around line `$2` if one is given (otherwise stop on entry and find the right spot yourself).

`crickit` drives the VSCode debugger from the command line — it is the interface for both humans and AI agents (see `crickit.md` for the full RPC contract). Requires VSCode to be open with the crickit extension running (the bridge); if commands fail with "bridge is not running", tell the user to open VSCode first.

## Workflow

0. **Start a transcript** so the session can be replayed or shared later — pick a path under `transcripts/` named after the bug/scenario:
   ```
   crickit record start transcripts/$1-debug.json
   ```
   Every command you run from here on (launch, breakpoints, stops, stack, vars) is appended to that JSON file as a structured `{command, at, result}` step — you don't need to do anything else to keep it updated. Run `crickit record stop` once you're done investigating.

1. **Launch** the target, stopped at the first line:
   ```
   crickit launch $1 --stop-on-entry
   ```

2. **Set a breakpoint** where you want to inspect state. If `$2` was given, use it directly:
   ```
   crickit bp add $1 $2
   ```
   Otherwise pick a likely line based on reading the source first (e.g. where a suspected bug occurs), or step through from entry instead of setting one.

3. **Run to the breakpoint**:
   ```
   crickit continue
   ```
   This blocks until the program stops (breakpoint hit, step complete, or termination) and prints `Stopped  reason=<reason>  <file>:<line>`.

4. **Inspect** at each stop:
   ```
   crickit stack          # call stack — which frame you're in and how you got there
   crickit vars           # local variables in the current (or --frame N) frame
   ```

5. **Step around** to narrow down the problem:
   ```
   crickit step           # step over (next line)
   crickit step-in        # step into a call
   crickit step-out       # step out of the current frame
   crickit continue       # resume until the next breakpoint/stop
   ```
   Re-run `crickit stack` / `crickit vars` after each stop to see how state changes.

6. **Manage breakpoints** as needed:
   ```
   crickit bp list
   crickit bp rm <id>
   ```

## Notes

- `continue` / `step` / `step-in` / `step-out` block until the program stops again, then print the new location — read the output before issuing the next command.
- `stack` and `vars` only work while stopped; if you see "no active stop", `continue` or `step` first.
- If the session terminates ("Session terminated."), the debug loop is over — summarize what you found instead of issuing more stepping commands.
- `crickit sessions` lists active sessions if you lose track of state.

## Reporting back

Once you've gathered enough evidence (the values of key variables at the point of failure, the call stack leading to the bug, etc.), explain to the user what's actually happening — don't just dump raw command output. Point at the specific line/variable that causes the issue and propose a fix if one is obvious.

Run `crickit record stop` to close out the transcript, then mention its path to the user — it's a structured, replayable record of the exact steps that reproduce the bug (`{"startedAt": ..., "steps": [{"command": ..., "at": ..., "result": {...}}]}`), useful for writing a regression test or for someone else to walk through the same scenario.
