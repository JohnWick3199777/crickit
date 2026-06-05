import os

import click
from rich.console import Console
from rich.table import Table

console = Console()

_BRIDGE_NOT_RUNNING = (
    "[red]crickit bridge is not running[/red] — "
    "open VSCode with the crickit extension installed"
)


def _handle_bridge_errors(fn):
    """Decorator that converts socket/bridge errors into clean CLI messages."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except FileNotFoundError:
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
