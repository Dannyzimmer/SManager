import os

import click

from ..config import DEFAULT_CONFIG_DIR, DEFAULT_CONFIG_PATH, resolve_config_path

_TEMPLATE = """\
global:
  # Absolute path to the directory where service metadata files in JSON live.
  services_dir: "/path/to/your/services"

  # VPN provider to use. Must match a registered provider (e.g. "tailscale").
  vpn_provider: "tailscale"

  # Filename for service metadata files. Each service should have a metadata file with this name in its directory.
  metadata_filename: "sd_info.json"
"""


@click.group("config")
def config_cmd() -> None:
    """Manage the smanager configuration file."""


@config_cmd.command("init")
@click.option("--force", is_flag=True, help="Overwrite existing config.")
def init_cmd(force: bool) -> None:
    """Create a template config at the default location.

    \b
    Default: ~/.config/smanager/smanager.yaml
    """
    if os.path.exists(DEFAULT_CONFIG_PATH) and not force:
        raise click.ClickException(
            f"Config already exists at {DEFAULT_CONFIG_PATH}. "
            "Use --force to overwrite."
        )
    os.makedirs(DEFAULT_CONFIG_DIR, exist_ok=True)
    with open(DEFAULT_CONFIG_PATH, "w") as f:
        f.write(_TEMPLATE)
    click.echo(f"Config created: {DEFAULT_CONFIG_PATH}")


@config_cmd.command("edit")
@click.pass_context
def edit_cmd(ctx: click.Context) -> None:
    """Open the config file in $EDITOR (falls back to nano).

    \b
    Resolves the config path in the same order as all other commands:
      1. --config PATH
      2. $SMANAGER_CONFIG
      3. ~/.config/smanager/smanager.yaml
      4. /etc/smanager/smanager.yaml
      5. ./smanager.yaml
    """
    try:
        path = resolve_config_path(ctx.obj.get("config_path"))
    except click.ClickException:
        raise click.ClickException(
            "No config file found. Run 'smanager config init' first."
        )
    editor = os.environ.get("EDITOR", "nano")
    click.edit(filename=path, editor=editor)
