"""Tabular rendering helpers for service status output."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from ...datatypes import MultiStatus, ServiceStatus


ACTIVE_STATUSES = {"running", "active"}


def _is_active(status: str) -> bool:
    return status.lower() in ACTIVE_STATUSES


def _name_cell(service_id: str, unit_name: str, is_active: bool) -> Text:
    icon = "●" if is_active else "○"
    color = "green" if is_active else "red"
    return Text.assemble((f"{icon} ", color), f"{service_id}/{unit_name}")


def _status_cell(status: str, is_active: bool) -> Text:
    color = "green" if is_active else "red"
    return Text(status, style=color)


def render_status_table(status: ServiceStatus | MultiStatus, console: Console | None = None) -> None:
    """Render service status data as a modern table with colors and icons."""
    if console is None:
        console = Console()

    services = [status] if isinstance(status, ServiceStatus) else status.services

    table = Table(title="Service Status", header_style="bold cyan", show_lines=False)
    table.add_column("name", style="bold", no_wrap=False)
    table.add_column("status", no_wrap=True)
    table.add_column("type", style="dim", no_wrap=True)

    rows: list[tuple[bool, str, str, str]] = []
    for svc in services:
        for unit in svc.statuses:
            full_name = f"{svc.id}/{unit.name}"
            rows.append((_is_active(unit.status), full_name, unit.status, svc.type))

    # Show inactive rows first, then keep output stable by name.
    for active, full_name, unit_status, svc_type in sorted(
        rows,
        key=lambda item: (item[0], item[1].lower()),
    ):
        service_id, unit_name = full_name.split("/", 1)
        table.add_row(
            _name_cell(service_id, unit_name, active),
            _status_cell(unit_status, active),
            svc_type,
        )

    console.print(table)
