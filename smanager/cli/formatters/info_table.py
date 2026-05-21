"""Tabular rendering helpers for service info output."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .runtime_style import runtime_style, runtime_style_for_activity, runtime_style_map


def _active_cell(active: bool) -> Text:
    return Text("yes", style="green") if active else Text("no", style="red")


def _type_cell(runtime_type: str, active: bool, registered_styles: dict[str, str]) -> Text:
    base_style = registered_styles.get(runtime_type, runtime_style(runtime_type))
    style = runtime_style_for_activity(runtime_type, active, base_style=base_style)
    return Text(runtime_type, style=style)


def render_info_table(
    rows: list[dict[str, Any]],
    details: bool = False,
    console: Console | None = None,
) -> None:
    """Render service info rows as a rich table."""
    if console is None:
        console = Console()

    registered_styles = runtime_style_map()

    table = Table(title="Service Info", header_style="bold cyan", show_lines=False)
    table.add_column("name", style="bold")
    table.add_column("webui", style="cyan", overflow="fold")
    table.add_column("type", no_wrap=True)
    table.add_column("active", no_wrap=True)
    table.add_column("groups")
    table.add_column("depends_on")

    if details:
        table.add_column("id")
        table.add_column("sys_user", style="dim", no_wrap=True)
        table.add_column("sys_group", style="dim", no_wrap=True)
        table.add_column("vpn_https", no_wrap=True)
        table.add_column("endpoint", no_wrap=True)
        table.add_column("runtime", overflow="fold")

    for row in sorted(rows, key=lambda item: str(item.get("name", "")).lower()):
        base = [
            str(row.get("name", "-")),
            str(row.get("webui_url", "-")),
            _type_cell(
                str(row.get("type", "-")),
                bool(row.get("active", False)),
                registered_styles,
            ),
            _active_cell(bool(row.get("active", False))),
            str(row.get("groups", "-")),
            str(row.get("depends_on", "-")),
        ]
        if details:
            base.extend(
                [
                    str(row.get("id", "-")),
                    str(row.get("sys_user", "-")),
                    str(row.get("sys_group", "-")),
                    "yes" if bool(row.get("vpn_https", False)) else "no",
                    str(row.get("endpoint_source", "-")),
                    str(row.get("runtime_detail", "-")),
                ]
            )
        table.add_row(*base)

    console.print(table)