import click

from . import ACTIONS
from ..config import get_manager


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
    try:
        manager.manage_all(action)
        click.echo(f"[OK] '{action}' on all services.")
    except ValueError as e:
        raise click.ClickException(str(e))
    except RuntimeError as e:
        raise click.ClickException(str(e))
