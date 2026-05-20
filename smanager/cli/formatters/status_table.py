"""Tabular rendering helpers for service status output."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from ...datatypes import MultiStatus, ServiceStatus


ACTIVE_STATUSES = {"running", "active"}


def _is_active(status: str) -> bool:
    return status.lower() in ACTIVE_STATUSES


def _name_cell(service_id: str, unit_name: str, icon: str, color: str) -> Text:
    return Text.assemble((f"{icon} ", color), f"{service_id}/{unit_name}")


def _status_cell(status: str, color: str) -> Text:
    return Text(status, style=color)


def _row_style(enabled: bool, unit_status: str) -> tuple[int, str, str, str]:
    active = _is_active(unit_status)
    if active:
        return (2, "●", "green", unit_status)
    if not enabled:
        return (1, "◌", "bright_black", "disabled")
    return (0, "○", "red", unit_status)


def render_status_table(status: ServiceStatus | MultiStatus, console: Console | None = None) -> None:
    """Render service status data as a modern table with colors and icons."""
    if console is None:
        console = Console()

    services = [status] if isinstance(status, ServiceStatus) else status.services

    table = Table(title="Service Status", header_style="bold cyan", show_lines=False)
    table.add_column("name", style="bold", no_wrap=False)
    table.add_column("status", no_wrap=True)
    table.add_column("type", style="dim", no_wrap=True)

    rows: list[tuple[int, str, str, str, str, str]] = []
    for svc in services:
        for unit in svc.statuses:
            full_name = f"{svc.id}/{unit.name}"
            priority, icon, color, label = _row_style(svc.enabled, unit.status)
            rows.append((priority, full_name, label, svc.type, icon, color))

    # Show stopped first, then disabled, then active; keep output stable by name.
    for _, full_name, status_label, svc_type, icon, color in sorted(
        rows,
        key=lambda item: (item[0], item[1].lower()),
    ):
        service_id, unit_name = full_name.split("/", 1)
        table.add_row(
            _name_cell(service_id, unit_name, icon, color),
            _status_cell(status_label, color),
            svc_type,
        )

    console.print(table)
