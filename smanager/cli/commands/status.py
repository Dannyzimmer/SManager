import dataclasses
import json as json_module

import click

from ..config import get_manager
from ...datatypes import MultiStatus, ServiceStatus


def _print_service_status(status: ServiceStatus) -> None:
    click.echo(f"Service: {status.id}  [{status.type}]")
    for s in status.statuses:
        marker = "●" if s.status in ("running", "active") else "○"
        click.echo(f"  {marker} {s.name}: {s.status}")


def _print_multi_status(multi: MultiStatus) -> None:
    for i, svc in enumerate(multi.services):
        if i > 0:
            click.echo("")
        _print_service_status(svc)


@click.command()
@click.option("--service", "service_id", default=None, metavar="ID",
              help="Status of a single service.")
@click.option("--group", "group_name", default=None, metavar="NAME",
              help="Status of all services in a group.")
@click.option("--dependency", "dependency_name", default=None, metavar="NAME",
              help="Status of services by dependency.")
@click.option("--all", "all_services", is_flag=True, default=False,
              help="Status of all services.")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Output as JSON.")
@click.pass_context
def status_cmd(
    ctx: click.Context,
    service_id: str | None,
    group_name: str | None,
    dependency_name: str | None,
    all_services: bool,
    as_json: bool,
) -> None:
    """Show the status of services.

    \b
    Provide exactly one scope:
      --service ID        single service
      --group NAME        all services in a group
      --dependency NAME   all services by dependency
      --all               every managed service
    """
    scopes = [x for x in [service_id, group_name, dependency_name] if x] + (
        [True] if all_services else []
    )
    if len(scopes) == 0:
        raise click.UsageError(
            "Provide one of: --service, --group, --dependency, --all"
        )
    if len(scopes) > 1:
        raise click.UsageError(
            "Only one of --service, --group, --dependency, --all can be used at a time."
        )

    manager = get_manager(ctx)
    try:
        if service_id:
            result = manager.get_status(service_id)
            if as_json:
                click.echo(json_module.dumps(dataclasses.asdict(result), indent=2))
            else:
                _print_service_status(result)
        else:
            if group_name:
                result = manager.get_group_status(group_name)
            elif dependency_name:
                result = manager.get_dependency_status(dependency_name)
            else:
                result = manager.get_all_status()
            if as_json:
                click.echo(json_module.dumps(dataclasses.asdict(result), indent=2))
            else:
                _print_multi_status(result)
    except ValueError as e:
        raise click.ClickException(str(e))
