import click

from ..config import get_manager
from ..events import attach_cli_event_renderer
from .info import emit_dependency_info
from .status import emit_dependency_status


@click.group(name="dependency")
@click.pass_context
def dependency_cmd(ctx: click.Context) -> None:
    """Manage services by dependency.

    \b
    Actions: start, stop, restart, enable, disable, status, info
    """


def _run_dependency_action(ctx: click.Context, action: str, dependency_name: str) -> None:
    manager = get_manager(ctx)
    detach_renderer = attach_cli_event_renderer(manager, command_scope="dependency")
    try:
        manager.manage_by_dependency(dependency_name, action)
    except ValueError as e:
        raise click.ClickException(str(e))
    except RuntimeError as e:
        raise click.ClickException(str(e))
    finally:
        detach_renderer()


@dependency_cmd.command(name="start")
@click.argument("dependency_name")
@click.pass_context
def dependency_start(ctx: click.Context, dependency_name: str) -> None:
    """Start services that depend on DEPENDENCY_NAME."""
    _run_dependency_action(ctx, "start", dependency_name)


@dependency_cmd.command(name="stop")
@click.argument("dependency_name")
@click.pass_context
def dependency_stop(ctx: click.Context, dependency_name: str) -> None:
    """Stop services that depend on DEPENDENCY_NAME."""
    _run_dependency_action(ctx, "stop", dependency_name)


@dependency_cmd.command(name="restart")
@click.argument("dependency_name")
@click.pass_context
def dependency_restart(ctx: click.Context, dependency_name: str) -> None:
    """Restart services that depend on DEPENDENCY_NAME."""
    _run_dependency_action(ctx, "restart", dependency_name)


@dependency_cmd.command(name="enable")
@click.argument("dependency_name")
@click.pass_context
def dependency_enable(ctx: click.Context, dependency_name: str) -> None:
    """Enable services that depend on DEPENDENCY_NAME."""
    _run_dependency_action(ctx, "enable", dependency_name)


@dependency_cmd.command(name="disable")
@click.argument("dependency_name")
@click.pass_context
def dependency_disable(ctx: click.Context, dependency_name: str) -> None:
    """Disable services that depend on DEPENDENCY_NAME."""
    _run_dependency_action(ctx, "disable", dependency_name)


@dependency_cmd.command(name="status")
@click.argument("dependency_name")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
@click.pass_context
def dependency_status(ctx: click.Context, dependency_name: str, as_json: bool) -> None:
    """Show status for services by dependency."""
    emit_dependency_status(ctx, dependency_name, as_json)


@dependency_cmd.command(name="info")
@click.argument("dependency_name")
@click.option("--details", is_flag=True, default=False, help="Include extra metadata columns.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
@click.pass_context
def dependency_info(
    ctx: click.Context,
    dependency_name: str,
    details: bool,
    as_json: bool,
) -> None:
    """Show info for services by dependency."""
    emit_dependency_info(ctx, dependency_name, as_json, details)
