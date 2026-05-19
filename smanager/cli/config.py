"""
Config loading and GlobalManager initialisation for the CLI.
"""
import os

import click

from ..datatypes import GlobalConfig
from ..global_manager import GlobalManager
from ..vpn import get_vpn


# ---------------------------------------------------------------------------
# Default paths (XDG-compliant)
# ---------------------------------------------------------------------------
_XDG_CONFIG_HOME = os.environ.get(
    "XDG_CONFIG_HOME", os.path.expanduser("~/.config")
)
DEFAULT_CONFIG_DIR = os.path.join(_XDG_CONFIG_HOME, "smanager")
DEFAULT_CONFIG_PATH = os.path.join(DEFAULT_CONFIG_DIR, "smanager.yaml")
SYSTEM_CONFIG_PATH = "/etc/smanager/smanager.yaml"

# Ordered list of locations tried when no explicit path is given.
_SEARCH_PATHS = [
    DEFAULT_CONFIG_PATH,
    SYSTEM_CONFIG_PATH,
    "smanager.yaml",  # legacy local fallback
]


def resolve_config_path(config_path: str | None) -> str:
    """Return the resolved config file path or raise ClickException."""
    if config_path is not None:
        return config_path
    env = os.environ.get("SMANAGER_CONFIG")
    if env:
        return env
    for path in _SEARCH_PATHS:
        if os.path.isfile(path):
            return path
    raise click.ClickException(
        f"No config file found. Run 'smanager config init' to create one at "
        f"{DEFAULT_CONFIG_PATH}."
    )


def build_manager(config_path: str | None) -> GlobalManager:
    """Resolve a config file and return an initialised GlobalManager."""
    path = resolve_config_path(config_path)
    with open(path) as f:
        try:
            config = GlobalConfig.from_yaml(f.read())
        except ValueError as e:
            raise click.ClickException(str(e))
    if not config.services_dir:
        raise click.ClickException("'services_dir' is not set in the config file.")
    if not os.path.isdir(config.services_dir):
        raise click.ClickException(
            f"services_dir does not exist: {config.services_dir}"
        )
    try:
        vpn_cls = get_vpn(config.vpn_provider)
        vpn = vpn_cls()
    except ValueError as e:
        raise click.ClickException(
            f"Unknown VPN provider '{config.vpn_provider}': {e}"
        )
    try:
        return GlobalManager(config.services_dir, config, vpn)
    except ValueError as e:
        raise click.ClickException(str(e)) from e


def get_manager(ctx: click.Context) -> GlobalManager:
    """Return the GlobalManager stored in *ctx*, building it lazily on first call."""
    if ctx.obj.get("_manager") is None:
        ctx.obj["_manager"] = build_manager(ctx.obj.get("config_path"))
    return ctx.obj["_manager"]
