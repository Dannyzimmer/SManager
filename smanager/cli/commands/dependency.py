import click

from . import ACTIONS
from ..config import get_manager
from ..events import attach_cli_event_renderer


@click.command()
@click.argument("action", type=click.Choice(ACTIONS, case_sensitive=False))
@click.argument("dependency_name")
@click.pass_context
def dependency_cmd(ctx: click.Context, action: str, dependency_name: str) -> None:
    """Perform ACTION on all services that depend on DEPENDENCY_NAME.

    \b
    Actions: start, stop, restart, enable, disable
    """
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
