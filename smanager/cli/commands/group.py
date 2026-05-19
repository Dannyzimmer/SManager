import click

from . import ACTIONS
from ..config import get_manager


@click.command()
@click.argument("action", type=click.Choice(ACTIONS, case_sensitive=False))
@click.argument("group_name")
@click.pass_context
def group_cmd(ctx: click.Context, action: str, group_name: str) -> None:
    """Perform ACTION on all services in GROUP_NAME.

    \b
    Actions: start, stop, restart, enable, disable
    """
    manager = get_manager(ctx)
    try:
        manager.manage_group(group_name, action)
        click.echo(f"[OK] '{action}' on group '{group_name}'.")
    except ValueError as e:
        raise click.ClickException(str(e))
    except RuntimeError as e:
        raise click.ClickException(str(e))
