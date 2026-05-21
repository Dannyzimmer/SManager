import dataclasses
import json as json_module

import click

from ..config import get_manager
from ..formatters import render_status_table


def _emit_status(result: object, as_json: bool) -> None:
    if as_json:
        click.echo(json_module.dumps(dataclasses.asdict(result), indent=2))
    else:
        render_status_table(result)


def emit_service_status(ctx: click.Context, service_id: str, as_json: bool) -> None:
    manager = get_manager(ctx)
    try:
        result = manager.get_status(service_id)
        _emit_status(result, as_json)
    except ValueError as e:
        raise click.ClickException(str(e))


def emit_group_status(ctx: click.Context, group_name: str, as_json: bool) -> None:
    manager = get_manager(ctx)
    try:
        result = manager.get_group_status(group_name)
        _emit_status(result, as_json)
    except ValueError as e:
        raise click.ClickException(str(e))


def emit_dependency_status(ctx: click.Context, dependency_name: str, as_json: bool) -> None:
    manager = get_manager(ctx)
    try:
        result = manager.get_dependency_status(dependency_name)
        _emit_status(result, as_json)
    except ValueError as e:
        raise click.ClickException(str(e))


def emit_all_status(ctx: click.Context, as_json: bool) -> None:
    manager = get_manager(ctx)
    try:
        result = manager.get_all_status()
        _emit_status(result, as_json)
    except ValueError as e:
        raise click.ClickException(str(e))
