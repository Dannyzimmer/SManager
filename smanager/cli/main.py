import click

from .commands import all_cmd, config_cmd, dependency_cmd, group_cmd, metadata_cmd, service_cmd, status_cmd


@click.group()
@click.option(
    "--config",
    "config_path",
    envvar="SMANAGER_CONFIG",
    default=None,
    metavar="PATH",
    help="Path to config file (or set SMANAGER_CONFIG). Default: ./smanager.yaml",
)
@click.version_option(package_name="smanager")
@click.pass_context
def cli(ctx: click.Context, config_path: str | None) -> None:
    """SManager — manage self-hosted services and Docker containers."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    ctx.obj["_manager"] = None


cli.add_command(service_cmd, "service")
cli.add_command(group_cmd, "group")
cli.add_command(dependency_cmd, "dependency")
cli.add_command(all_cmd, "all")
cli.add_command(status_cmd, "status")
cli.add_command(config_cmd, "config")
cli.add_command(metadata_cmd, "metadata")
