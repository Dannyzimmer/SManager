"""Helpers to route privileged CLI actions through the SManager daemon.

The daemon is used when explicitly requested (``--daemon``) or when a socket is
present and not disabled (``--no-daemon``). Without a daemon the CLI falls back
to local execution, preserving the previous behavior.
"""

from __future__ import annotations

import os

import click

from ..daemon.client import (
    DEFAULT_SOCKET_PATH,
    DaemonClient,
    DaemonConnectionError,
    DaemonError,
)
from .config import get_manager
from .events import attach_cli_event_renderer, format_event_dict


def socket_path(ctx: click.Context) -> str:
    return (
        ctx.obj.get("daemon_socket")
        or os.environ.get("SMANAGER_SOCKET")
        or DEFAULT_SOCKET_PATH
    )


def _mode(ctx: click.Context):
    return ctx.obj.get("daemon")  # None (auto), True (force), False (disable)


def use_daemon(ctx: click.Context) -> bool:
    mode = _mode(ctx)
    if mode is False:
        return False
    if mode is True:
        return True
    return os.path.exists(socket_path(ctx))


def get_daemon_client(ctx: click.Context) -> DaemonClient | None:
    """Return a connected client, or None to fall back to local execution."""
    if not use_daemon(ctx):
        return None
    client = DaemonClient(socket_path(ctx))
    try:
        client.connect()
    except (DaemonConnectionError, DaemonError) as exc:
        if _mode(ctx) is True:
            raise click.ClickException(
                f"{exc}. The daemon is not responding; check 'smanager daemon status' "
                "and 'smanager daemon logs', or run with --no-daemon."
            )
        click.echo(
            f"warning: smanagerd unavailable ({exc}); falling back to local execution",
            err=True,
        )
        return None
    return client


def run_action(
    ctx: click.Context,
    scope: str,
    action: str,
    *,
    service_id: str | None = None,
    group_name: str | None = None,
    dependency_name: str | None = None,
    dry_run: bool = False,
) -> None:
    """Run an action through the daemon when available, else locally."""
    client = get_daemon_client(ctx)
    if client is not None:
        def on_event(event: dict) -> None:
            message = format_event_dict(event, scope)
            if message:
                click.echo(message)

        try:
            if scope == "service":
                client.action(service_id, action, dry_run=dry_run, on_event=on_event)
            elif scope == "group":
                client.group_action(group_name, action, dry_run=dry_run, on_event=on_event)
            elif scope == "dependency":
                client.dependency_action(dependency_name, action, dry_run=dry_run, on_event=on_event)
            else:
                client.all_action(action, dry_run=dry_run, on_event=on_event)
        except DaemonError as exc:
            raise click.ClickException(str(exc))
        finally:
            client.close()
        return

    manager = get_manager(ctx)
    detach_renderer = attach_cli_event_renderer(manager, command_scope=scope)
    try:
        if scope == "service":
            manager.manage_service(service_id, action, dry_run=dry_run)
        elif scope == "group":
            manager.manage_group(group_name, action, dry_run=dry_run)
        elif scope == "dependency":
            manager.manage_by_dependency(dependency_name, action, dry_run=dry_run)
        else:
            manager.manage_all(action, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001 - surfaced as a Click error
        raise click.ClickException(str(exc))
    finally:
        detach_renderer()
