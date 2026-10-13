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
    try:
        with open(path) as f:
            raw_config = f.read()
    except OSError as e:
        raise click.ClickException(f"Cannot read config file '{path}': {e}")
    try:
        config = GlobalConfig.from_yaml(raw_config)
    except ValueError as e:
        raise click.ClickException(str(e))
    if not config.services_root:
        raise click.ClickException("'services_root' is not set in the config file.")
    if not os.path.isdir(config.services_root):
        raise click.ClickException(
            f"services_root does not exist: {config.services_root}"
        )
    try:
        vpn_cls = get_vpn(config.vpn_provider)
        vpn = vpn_cls()
    except ValueError as e:
        raise click.ClickException(
            f"Unknown VPN provider '{config.vpn_provider}': {e}"
        )
    try:
        return GlobalManager(config.services_root, config, vpn)
    except ValueError as e:
        raise click.ClickException(str(e)) from e


def get_manager(ctx: click.Context) -> GlobalManager:
    """Return the GlobalManager stored in *ctx*, building it lazily on first call."""
    if ctx.obj.get("_manager") is None:
        ctx.obj["_manager"] = build_manager(ctx.obj.get("config_path"))
    return ctx.obj["_manager"]


def get_metadata_filename(ctx: click.Context) -> str:
    """Return the configured metadata_filename from GlobalConfig.

    Falls back to the GlobalConfig default when no config file exists yet
    (e.g. during bootstrap with ``smanager metadata init``).
    Raises ClickException if a config file exists but cannot be parsed.
    """
    config_path = ctx.obj.get("config_path")
    try:
        path = resolve_config_path(config_path)
    except click.ClickException:
        return GlobalConfig.__dataclass_fields__["metadata_filename"].default
    try:
        with open(path) as f:
            raw_config = f.read()
    except OSError as e:
        raise click.ClickException(f"Cannot read config file '{path}': {e}")
    try:
        config = GlobalConfig.from_yaml(raw_config)
    except ValueError as e:
        raise click.ClickException(str(e))
    return config.metadata_filename
