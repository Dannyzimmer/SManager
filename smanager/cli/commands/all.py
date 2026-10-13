import click

from ..config import get_manager
from ..events import attach_cli_event_renderer
from .info import emit_all_info
from .status import emit_all_status


@click.group(name="all")
@click.pass_context
def all_cmd(ctx: click.Context) -> None:
    """Manage all services.

    \b
    Actions: start, stop, restart, update, enable, disable, status, info

    Management actions require --yes to prevent accidental execution.
    """


def _run_all_action(
    ctx: click.Context,
    action: str,
    yes: bool,
    dry_run: bool = False,
) -> None:
    if not yes and not dry_run:
        raise click.UsageError(
            f"This will run '{action}' on ALL services. Pass --yes to confirm."
        )
    manager = get_manager(ctx)
    detach_renderer = attach_cli_event_renderer(manager, command_scope="all")
    try:
        manager.manage_all(action, dry_run=dry_run)
    except Exception as e:
        raise click.ClickException(str(e))
    finally:
        detach_renderer()


@all_cmd.command(name="start")
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm the operation on all services.",
)
@click.pass_context
def all_start(ctx: click.Context, yes: bool) -> None:
    """Start all managed services.

    Requires --yes to prevent accidental execution.
    """
    _run_all_action(ctx, "start", yes)


@all_cmd.command(name="stop")
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm the operation on all services.",
)
@click.pass_context
def all_stop(ctx: click.Context, yes: bool) -> None:
    """Stop all managed services.

    Requires --yes to prevent accidental execution.
    """
    _run_all_action(ctx, "stop", yes)


@all_cmd.command(name="restart")
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm the operation on all services.",
)
@click.pass_context
def all_restart(ctx: click.Context, yes: bool) -> None:
    """Restart all managed services.

    Requires --yes to prevent accidental execution.
    """
    _run_all_action(ctx, "restart", yes)


@all_cmd.command(name="update")
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm the operation on all services.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Show what would run without executing it.")
@click.pass_context
def all_update(ctx: click.Context, yes: bool, dry_run: bool) -> None:
    """Update all managed services.

    Requires --yes unless --dry-run is used.
    """
    _run_all_action(ctx, "update", yes, dry_run=dry_run)


@all_cmd.command(name="enable")
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm the operation on all services.",
)
@click.pass_context
def all_enable(ctx: click.Context, yes: bool) -> None:
    """Enable all managed services.

    Requires --yes to prevent accidental execution.
    """
    _run_all_action(ctx, "enable", yes)


@all_cmd.command(name="disable")
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm the operation on all services.",
)
@click.pass_context
def all_disable(ctx: click.Context, yes: bool) -> None:
    """Disable all managed services.

    Requires --yes to prevent accidental execution.
    """
    _run_all_action(ctx, "disable", yes)


@all_cmd.command(name="status")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
@click.pass_context
def all_status(ctx: click.Context, as_json: bool) -> None:
    """Show status for all managed services."""
    emit_all_status(ctx, as_json)


@all_cmd.command(name="info")
@click.option("--details", is_flag=True, default=False, help="Include extra metadata columns.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
@click.pass_context
def all_info(ctx: click.Context, details: bool, as_json: bool) -> None:
    """Show info for all managed services."""
    emit_all_info(ctx, as_json, details)
