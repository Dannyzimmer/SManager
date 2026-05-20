import click

from . import ACTIONS
from ..config import get_manager
from ..events import attach_cli_event_renderer


@click.command("all")
@click.argument("action", type=click.Choice(ACTIONS, case_sensitive=False))
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm the operation on all services.",
)
@click.pass_context
def all_cmd(ctx: click.Context, action: str, yes: bool) -> None:
    """Perform ACTION on ALL managed services.

    \b
    Actions: start, stop, restart, enable, disable

    Requires --yes to prevent accidental execution.
    """
    if not yes:
        raise click.UsageError(
            f"This will run '{action}' on ALL services. Pass --yes to confirm."
        )
    manager = get_manager(ctx)
    detach_renderer = attach_cli_event_renderer(manager, command_scope="all")
    try:
        manager.manage_all(action)
    except ValueError as e:
        raise click.ClickException(str(e))
    except RuntimeError as e:
        raise click.ClickException(str(e))
    finally:
        detach_renderer()
