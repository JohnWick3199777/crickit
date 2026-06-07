import os
import sys
from dataclasses import asdict

import click
from rich.console import Console
from rich.table import Table

from crickit_core import transcript

console = Console()


def _cmd() -> str:
    """The invoked subcommand and its arguments, as typed (minus `crickit`)."""
    return " ".join(sys.argv[1:])


_BRIDGE_NOT_RUNNING = (
    "[red]crickit bridge is not running[/red] — "
    "open VSCode with the crickit extension installed"
)

_NOT_STOPPED = (
    "[red]no active stop[/red] — "
    "launch with --stop-on-entry or hit a breakpoint first"
)


def _handle_bridge_errors(fn):
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except FileNotFoundError as e:
            if "No debug state" in str(e):
                console.print(_NOT_STOPPED)
            else:
                console.print(_BRIDGE_NOT_RUNNING)
            raise SystemExit(1)
        except ConnectionRefusedError:
            console.print(_BRIDGE_NOT_RUNNING)
            raise SystemExit(1)

    return wrapper


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.argument("program", type=click.Path(exists=True, dir_okay=False, resolve_path=True))
@click.option("--type", "debug_type", default=None, metavar="TYPE",
              help="Debug adapter type (e.g. debugpy, node). Inferred from file extension if omitted.")
@click.option("--stop-on-entry", is_flag=True, default=False,
              help="Pause at the first line of the program.")
@click.argument("args", nargs=-1)
@_handle_bridge_errors
def launch(program: str, debug_type: str | None, stop_on_entry: bool, args: tuple[str, ...]) -> None:
    """Launch a debug session for PROGRAM in VSCode."""
    from crickit_core import launch_debug_session

    console.print(f"Launching [bold]{os.path.basename(program)}[/bold]...")
    session = launch_debug_session(
        program,
        debug_type=debug_type,
        args=list(args) or None,
        stop_on_entry=stop_on_entry,
    )
    console.print(
        f"[green]Session started[/green]  "
        f"[bold]{session.name}[/bold]  "
        f"[dim]{session.id}[/dim]  "
        f"type={session.type}"
    )
    transcript.record_step(_cmd(), {"type": "launch", "session": asdict(session)})


@cli.command()
@_handle_bridge_errors
def sessions() -> None:
    """List active VSCode debug sessions."""
    from crickit_core import get_debug_sessions

    sessions = get_debug_sessions()

    if not sessions:
        console.print("[yellow]No active debug sessions.[/yellow]")
        return

    table = Table(title="Active Debug Sessions")
    table.add_column("Name", style="bold")
    table.add_column("ID", style="dim")
    table.add_column("Type")

    for s in sessions:
        table.add_row(s.name, s.id, s.type)

    console.print(table)


# ── transcript recording ─────────────────────────────────────────────────────

@cli.group()
def record() -> None:
    """Record a debugging session transcript to a JSON file."""
    pass


@record.command("start")
@click.argument("path", type=click.Path(dir_okay=False, resolve_path=True))
def record_start(path: str) -> None:
    """Start recording every subsequent command + result to PATH (JSON)."""
    transcript.start(path)
    console.print(f"[green]Recording started[/green]  {path}")


@record.command("stop")
def record_stop() -> None:
    """Stop recording the transcript."""
    path = transcript.stop()
    if path is None:
        console.print("[yellow]Not recording.[/yellow]")
    else:
        console.print(f"[yellow]Recording stopped[/yellow]  {path}")


# ── breakpoints ──────────────────────────────────────────────────────────────

@cli.group()
def bp() -> None:
    """Manage breakpoints."""
    pass


@bp.command("add")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, resolve_path=True))
@click.argument("line", type=int)
@click.option("--condition", default=None, metavar="EXPR", help="Conditional expression.")
@_handle_bridge_errors
def bp_add(file: str, line: int, condition: str | None) -> None:
    """Set a breakpoint at FILE:LINE."""
    from crickit_core import set_breakpoint

    bp = set_breakpoint(file, line, condition)
    console.print(
        f"[green]Breakpoint set[/green]  "
        f"id={bp.id}  "
        f"{os.path.basename(bp.file)}:{bp.line}  "
        f"verified={bp.verified}"
    )
    transcript.record_step(_cmd(), {"type": "breakpoint_set", "breakpoint": asdict(bp)})


@bp.command("rm")
@click.argument("id")
@_handle_bridge_errors
def bp_rm(id: str) -> None:
    """Remove breakpoint by ID."""
    from crickit_core import remove_breakpoint

    remove_breakpoint(id)
    console.print(f"[yellow]Breakpoint removed[/yellow]  id={id}")
    transcript.record_step(_cmd(), {"type": "breakpoint_removed", "id": id})


@bp.command("list")
@_handle_bridge_errors
def bp_list() -> None:
    """List all breakpoints."""
    from crickit_core import list_breakpoints

    bps = list_breakpoints()
    transcript.record_step(_cmd(), {"type": "breakpoints", "breakpoints": [asdict(b) for b in bps]})
    if not bps:
        console.print("[yellow]No breakpoints set.[/yellow]")
        return

    table = Table(title="Breakpoints")
    table.add_column("ID", style="dim")
    table.add_column("File", style="bold")
    table.add_column("Line", justify="right")
    table.add_column("Verified")

    for b in bps:
        table.add_row(b.id, os.path.basename(b.file), str(b.line), str(b.verified))

    console.print(table)


# ── stepping ─────────────────────────────────────────────────────────────────

def _print_stop(state, command: str) -> None:
    console.print(
        f"[cyan]Stopped[/cyan]  "
        f"reason={state.reason}  "
        f"{state.stopped_at}"
    )
    transcript.record_step(command, {"type": "stop", "state": asdict(state)})


def _record_terminated(command: str) -> None:
    transcript.record_step(command, {"type": "terminated"})


@cli.command("continue")
@_handle_bridge_errors
def do_continue() -> None:
    """Continue until next stop."""
    from crickit_core import continue_session
    from crickit_core.client import SessionTerminatedError

    try:
        state = continue_session()
        _print_stop(state, _cmd())
    except SessionTerminatedError:
        console.print("[yellow]Session terminated.[/yellow]")
        _record_terminated(_cmd())


@cli.command("step")
@_handle_bridge_errors
def step() -> None:
    """Step over (next line)."""
    from crickit_core import step_over
    from crickit_core.client import SessionTerminatedError

    try:
        state = step_over()
        _print_stop(state, _cmd())
    except SessionTerminatedError:
        console.print("[yellow]Session terminated.[/yellow]")
        _record_terminated(_cmd())


@cli.command("step-in")
@_handle_bridge_errors
def step_in() -> None:
    """Step into a call."""
    from crickit_core import step_into
    from crickit_core.client import SessionTerminatedError

    try:
        state = step_into()
        _print_stop(state, _cmd())
    except SessionTerminatedError:
        console.print("[yellow]Session terminated.[/yellow]")
        _record_terminated(_cmd())


@cli.command("step-out")
@_handle_bridge_errors
def step_out_cmd() -> None:
    """Step out of current frame."""
    from crickit_core import step_out
    from crickit_core.client import SessionTerminatedError

    try:
        state = step_out()
        _print_stop(state, _cmd())
    except SessionTerminatedError:
        console.print("[yellow]Session terminated.[/yellow]")
        _record_terminated(_cmd())


# ── inspection ───────────────────────────────────────────────────────────────

@cli.command("stack")
@_handle_bridge_errors
def stack() -> None:
    """Print the call stack at current stop."""
    from crickit_core import get_stack_trace
    from crickit_core.state import load_state

    state = load_state()
    frames = get_stack_trace()

    table = Table(show_header=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Function", style="bold")
    table.add_column("File")
    table.add_column("Line", justify="right")

    for i, f in enumerate(frames):
        marker = " ← current frame" if i == state.frame_id else ""
        table.add_row(
            str(i),
            f.name,
            os.path.basename(f.source),
            str(f.line) + marker,
        )

    console.print(table)
    transcript.record_step(_cmd(), {
        "type": "stack",
        "currentFrame": state.frame_id,
        "frames": [asdict(f) for f in frames],
    })


@cli.command("vars")
@click.option("--frame", "frame_id", default=None, type=int,
              help="Frame ID (default: top frame from last stop).")
@_handle_bridge_errors
def vars_cmd(frame_id: int | None) -> None:
    """Print local variables at current stop."""
    from crickit_core import get_scopes, get_stack_trace, get_variables
    from crickit_core.state import load_state

    state = load_state()
    if frame_id is not None:
        fid = frame_id
    else:
        # state.frame_id is an index into the stack (0 = top frame); resolve it
        # to the debug adapter's frame id, which `scopes` actually expects.
        fid = get_stack_trace()[state.frame_id].id
    scopes = get_scopes(fid)

    table = Table(show_header=True)
    table.add_column("Name", style="bold")
    table.add_column("Value")
    table.add_column("Type", style="dim")

    all_variables = []
    for scope in scopes:
        if scope.expensive:
            continue
        variables = get_variables(scope.variables_reference)
        all_variables.extend(variables)
        for v in variables:
            value = v.value if v.variables_reference == 0 else f"<{v.type} ref={v.variables_reference}>"
            table.add_row(v.name, value, v.type)

    console.print(table)
    transcript.record_step(_cmd(), {
        "type": "variables",
        "frameId": fid,
        "variables": [asdict(v) for v in all_variables],
    })
