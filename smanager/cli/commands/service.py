import click

from ..config import get_manager
from ..events import attach_cli_event_renderer
from .info import emit_service_info
from .status import emit_service_status


@click.group(name="service")
@click.pass_context
def service_cmd(ctx: click.Context) -> None:
    """Manage a single service.

    \b
    Actions: start, stop, restart, enable, disable, status, info
    """


def _run_service_action(ctx: click.Context, action: str, service_id: str) -> None:
    manager = get_manager(ctx)
    detach_renderer = attach_cli_event_renderer(manager, command_scope="service")
    try:
        manager.manage_service(service_id, action)
    except Exception as e:
        raise click.ClickException(str(e))
    finally:
        detach_renderer()


@service_cmd.command(name="start")
@click.argument("service_id")
@click.pass_context
def service_start(ctx: click.Context, service_id: str) -> None:
    """Start a single service."""
    _run_service_action(ctx, "start", service_id)


@service_cmd.command(name="stop")
@click.argument("service_id")
@click.pass_context
def service_stop(ctx: click.Context, service_id: str) -> None:
    """Stop a single service."""
    _run_service_action(ctx, "stop", service_id)


@service_cmd.command(name="restart")
@click.argument("service_id")
@click.pass_context
def service_restart(ctx: click.Context, service_id: str) -> None:
    """Restart a single service."""
    _run_service_action(ctx, "restart", service_id)


@service_cmd.command(name="enable")
@click.argument("service_id")
@click.pass_context
def service_enable(ctx: click.Context, service_id: str) -> None:
    """Enable a single service."""
    _run_service_action(ctx, "enable", service_id)


@service_cmd.command(name="disable")
@click.argument("service_id")
@click.pass_context
def service_disable(ctx: click.Context, service_id: str) -> None:
    """Disable a single service."""
    _run_service_action(ctx, "disable", service_id)


@service_cmd.command(name="status")
@click.argument("service_id")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
@click.pass_context
def service_status(ctx: click.Context, service_id: str, as_json: bool) -> None:
    """Show status for a single service."""
    emit_service_status(ctx, service_id, as_json)


@service_cmd.command(name="info")
@click.argument("service_id")
@click.option("--details", is_flag=True, default=False, help="Include extra metadata columns.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
@click.pass_context
def service_info(ctx: click.Context, service_id: str, details: bool, as_json: bool) -> None:
    """Show info for a single service."""
    emit_service_info(ctx, service_id, as_json, details)
