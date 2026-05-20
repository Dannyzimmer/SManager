import click

from . import ACTIONS
from ..config import get_manager
from ..events import attach_cli_event_renderer


@click.command()
@click.argument("action", type=click.Choice(ACTIONS, case_sensitive=False))
@click.argument("service_id")
@click.pass_context
def service_cmd(ctx: click.Context, action: str, service_id: str) -> None:
    """Perform ACTION on a single service.

    \b
    Actions: start, stop, restart, enable, disable
    """
    manager = get_manager(ctx)
    detach_renderer = attach_cli_event_renderer(manager, command_scope="service")
    try:
        manager.manage_service(service_id, action)
    except ValueError as e:
        raise click.ClickException(str(e))
    except RuntimeError as e:
        raise click.ClickException(str(e))
    finally:
        detach_renderer()
