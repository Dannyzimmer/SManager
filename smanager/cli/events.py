"""Helpers to render manager callbacks as CLI messages."""

from __future__ import annotations

from collections.abc import Callable

import click

from ..events import ManagerEvent


def attach_cli_event_renderer(manager, command_scope: str) -> Callable[[], None]:
    """Attach CLI output renderer to manager callbacks and return teardown."""

    def _handle_event(event: ManagerEvent) -> None:
        message = _format_event_for_cli(event, command_scope)
        if message:
            click.echo(message)

    manager.on(_handle_event)

    def _detach() -> None:
        manager.off(_handle_event)

    return _detach


def _format_event_for_cli(event: ManagerEvent, command_scope: str) -> str | None:
    if event.phase == "failed":
        return _format_failed_event(event)

    if event.scope == "service" and event.phase == "skipped":
        service_id = event.service_id or "<unknown>"
        reason = event.message or "Operation skipped."
        return f"[SKIP] '{event.action}' on service '{service_id}': {reason}"

    if event.phase != "after":
        return None

    if event.scope != command_scope:
        return None

    if event.scope == "service":
        service_id = event.service_id or "<unknown>"
        return f"[OK] '{event.action}' on service '{service_id}'."

    if event.scope == "group":
        group_name = event.group_name or "<unknown>"
        return f"[OK] '{event.action}' on group '{group_name}'."

    if event.scope == "dependency":
        dependency_name = event.dependency_name or "<unknown>"
        return f"[OK] '{event.action}' on services depending on '{dependency_name}'."

    if event.scope == "all":
        return f"[OK] '{event.action}' on all services."

    return None


def _format_failed_event(event: ManagerEvent) -> str:
    if event.scope == "service":
        target = f"service '{event.service_id or '<unknown>'}'"
    elif event.scope == "group":
        target = f"group '{event.group_name or '<unknown>'}'"
    elif event.scope == "dependency":
        target = (
            f"services depending on '{event.dependency_name or '<unknown>'}'"
        )
    elif event.scope == "all":
        target = "all services"
    else:
        target = event.scope

    if event.error is None:
        detail = "unknown error"
    else:
        detail = str(event.error)

    return f"[ERR] '{event.action}' on {target}: {detail}"
