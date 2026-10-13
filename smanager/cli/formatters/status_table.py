"""Tabular rendering helpers for service status output."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from ...datatypes import MultiStatus, ServiceStatus
from .runtime_style import runtime_style, runtime_style_for_activity, runtime_style_map


ACTIVE_STATUSES = {"running", "active"}


def _is_active(status: str) -> bool:
    return status.lower() in ACTIVE_STATUSES


def _name_cell(service_id: str, unit_name: str, icon: str, color: str) -> Text:
    return Text.assemble((f"{icon} ", color), f"{service_id}/{unit_name}")


def _status_cell(status: str, color: str) -> Text:
    return Text(status, style=color)


def _type_cell(runtime_type: str, enabled: bool, registered_styles: dict[str, str]) -> Text:
    base_style = registered_styles.get(runtime_type, runtime_style(runtime_type))
    style = runtime_style_for_activity(runtime_type, enabled, base_style=base_style)
    return Text(runtime_type, style=style)


def _row_style(enabled: bool, unit_status: str) -> tuple[int, str, str, str]:
    active = _is_active(unit_status)
    if active:
        return (2, "●", "green", unit_status)
    if not enabled:
        return (1, "◌", "bright_black", "disabled")
    return (0, "○", "red", unit_status)


def _update_cell(svc: ServiceStatus) -> Text:
    update = svc.update
    if update is None:
        return Text("")
    if update.error is not None or update.available is None:
        return Text("?", style="bright_black")
    if update.available:
        label = update.latest or update.current or "yes"
        return Text(f"↑ {label}", style="yellow")
    return Text("up-to-date", style="green")


def render_status_table(status: ServiceStatus | MultiStatus, console: Console | None = None) -> None:
    """Render service status data as a modern table with colors and icons."""
    if console is None:
        console = Console()

    services = [status] if isinstance(status, ServiceStatus) else status.services
    services_by_id = {svc.id: svc for svc in services}
    registered_styles = runtime_style_map()
    show_update = any(svc.update is not None for svc in services)

    table = Table(title="Service Status", header_style="bold cyan", show_lines=False)
    table.add_column("name", style="bold", no_wrap=False)
    table.add_column("type", no_wrap=True)
    table.add_column("status", no_wrap=True)
    if show_update:
        table.add_column("update", no_wrap=True)

    rows: list[tuple[int, str, str, str, str, str, bool, bool]] = []
    for svc in services:
        for index, unit in enumerate(svc.statuses):
            full_name = f"{svc.id}/{unit.name}"
            priority, icon, color, label = _row_style(svc.enabled, unit.status)
            # Only annotate the first unit row with the service-level update info.
            rows.append((priority, full_name, svc.type, label, icon, color, svc.enabled, index == 0))

    # Show stopped first, then disabled, then active; keep output stable by name.
    for _, full_name, svc_type, status_label, icon, color, svc_enabled, first_unit in sorted(
        rows,
        key=lambda item: (item[0], item[1].lower()),
    ):
        service_id, unit_name = full_name.split("/", 1)
        cells = [
            _name_cell(service_id, unit_name, icon, color),
            _type_cell(svc_type, svc_enabled, registered_styles),
            _status_cell(status_label, color),
        ]
        if show_update:
            svc = services_by_id.get(service_id)
            cells.append(_update_cell(svc) if first_unit and svc else Text(""))
        table.add_row(*cells)

    console.print(table)
