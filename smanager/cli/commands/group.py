import click

from ..config import get_manager
from ..events import attach_cli_event_renderer
from .info import emit_group_info
from .status import emit_group_status


@click.group(name="group")
@click.pass_context
def group_cmd(ctx: click.Context) -> None:
    """Manage all services in a group.

    \b
    Actions: start, stop, restart, enable, disable, status, info
    """


def _run_group_action(ctx: click.Context, action: str, group_name: str) -> None:
    manager = get_manager(ctx)
    detach_renderer = attach_cli_event_renderer(manager, command_scope="group")
    try:
        manager.manage_group(group_name, action)
    except Exception as e:
        raise click.ClickException(str(e))
    finally:
        detach_renderer()


@group_cmd.command(name="start")
@click.argument("group_name")
@click.pass_context
def group_start(ctx: click.Context, group_name: str) -> None:
    """Start all services in GROUP_NAME."""
    _run_group_action(ctx, "start", group_name)


@group_cmd.command(name="stop")
@click.argument("group_name")
@click.pass_context
def group_stop(ctx: click.Context, group_name: str) -> None:
    """Stop all services in GROUP_NAME."""
    _run_group_action(ctx, "stop", group_name)


@group_cmd.command(name="restart")
@click.argument("group_name")
@click.pass_context
def group_restart(ctx: click.Context, group_name: str) -> None:
    """Restart all services in GROUP_NAME."""
    _run_group_action(ctx, "restart", group_name)


@group_cmd.command(name="enable")
@click.argument("group_name")
@click.pass_context
def group_enable(ctx: click.Context, group_name: str) -> None:
    """Enable all services in GROUP_NAME."""
    _run_group_action(ctx, "enable", group_name)


@group_cmd.command(name="disable")
@click.argument("group_name")
@click.pass_context
def group_disable(ctx: click.Context, group_name: str) -> None:
    """Disable all services in GROUP_NAME."""
    _run_group_action(ctx, "disable", group_name)


@group_cmd.command(name="status")
@click.argument("group_name")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
@click.pass_context
def group_status(ctx: click.Context, group_name: str, as_json: bool) -> None:
    """Show status for all services in GROUP_NAME."""
    emit_group_status(ctx, group_name, as_json)


@group_cmd.command(name="info")
@click.argument("group_name")
@click.option("--details", is_flag=True, default=False, help="Include extra metadata columns.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
@click.pass_context
def group_info(ctx: click.Context, group_name: str, details: bool, as_json: bool) -> None:
    """Show info for all services in GROUP_NAME."""
    emit_group_info(ctx, group_name, as_json, details)
