from __future__ import annotations

import json as json_module
from typing import Any

import click

from ...datatypes import Service
from ..config import get_manager
from ..formatters import render_info_table


def _resolve_service(manager, service_id: str) -> Service:
    for service in manager.services:
        if service.metadata.id == service_id:
            return service
    raise ValueError(f"Service with ID '{service_id}' not found.")


def _endpoint_kind(endpoint: str) -> str:
    if endpoint.endswith(".ts.net"):
        return "magicdns"
    return "ip"


def _resolve_vpn_endpoint(manager) -> str | None:
    if not hasattr(manager, "vpn"):
        return None
    endpoint_getter = getattr(manager.vpn, "get_endpoint", None)
    if not callable(endpoint_getter):
        return None
    try:
        return endpoint_getter()
    except Exception:
        return None


def _build_webui_url(service: Service, vpn_endpoint: str | None) -> tuple[str, str]:
    metadata = service.metadata
    serve_https = bool(metadata.vpn and metadata.vpn.serve_https)
    scheme = "https" if serve_https else "http"
    if vpn_endpoint:
        host = vpn_endpoint
        endpoint_source = _endpoint_kind(vpn_endpoint)
    else:
        host = "localhost"
        endpoint_source = "fallback"

    url = f"{scheme}://{host}:{metadata.runtime.ports.webui}"
    return url, endpoint_source


def _runtime_detail(service: Service) -> str:
    metadata = service.metadata
    if metadata.runtime.type == "docker":
        compose = metadata.docker.compose_file if metadata.docker else None
        return compose or "-"
    if metadata.runtime.type == "php":
        if metadata.php and metadata.php.healthcheck_url:
            return metadata.php.healthcheck_url
        if metadata.php and metadata.php.start_command:
            return metadata.php.start_command
        return "-"
    if metadata.local and metadata.local.systemd_services:
        return ", ".join(metadata.local.systemd_services)
    return "-"


def _to_info_row(service: Service, details: bool, vpn_endpoint: str | None) -> dict[str, Any]:
    metadata = service.metadata
    webui_url, endpoint_source = _build_webui_url(service, vpn_endpoint)

    row: dict[str, Any] = {
        "name": metadata.name,
        "webui_url": webui_url,
        "type": metadata.runtime.type,
        "active": bool(metadata.active),
        "groups": ", ".join(metadata.groups or []) or "-",
        "depends_on": ", ".join(metadata.depends_on or []) or "-",
    }

    if details:
        row.update(
            {
                "id": metadata.id,
                "sys_user": metadata.runtime.sys_user,
                "sys_group": metadata.runtime.sys_group,
                "vpn_https": bool(metadata.vpn and metadata.vpn.serve_https),
                "endpoint_source": endpoint_source,
                "runtime_detail": _runtime_detail(service),
            }
        )

    return row


def _emit_info_rows(
    rows: list[dict[str, Any]],
    as_json: bool,
    details: bool,
    *,
    single_item_json: bool,
) -> None:
    if as_json:
        payload: Any = rows[0] if single_item_json and len(rows) == 1 else rows
        click.echo(json_module.dumps(payload, indent=2))
    else:
        render_info_table(rows, details=details)


def emit_service_info(
    ctx: click.Context,
    service_id: str,
    as_json: bool,
    details: bool,
) -> None:
    manager = get_manager(ctx)
    try:
        vpn_endpoint = _resolve_vpn_endpoint(manager)
        service = _resolve_service(manager, service_id)
        row = _to_info_row(service, details, vpn_endpoint)
        _emit_info_rows([row], as_json, details, single_item_json=True)
    except Exception as e:
        raise click.ClickException(str(e))


def emit_group_info(
    ctx: click.Context,
    group_name: str,
    as_json: bool,
    details: bool,
) -> None:
    manager = get_manager(ctx)
    try:
        vpn_endpoint = _resolve_vpn_endpoint(manager)
        services = manager.get_group(group_name)
        rows = [_to_info_row(service, details, vpn_endpoint) for service in services]
        _emit_info_rows(rows, as_json, details, single_item_json=False)
    except Exception as e:
        raise click.ClickException(str(e))


def emit_dependency_info(
    ctx: click.Context,
    dependency_name: str,
    as_json: bool,
    details: bool,
) -> None:
    manager = get_manager(ctx)
    try:
        vpn_endpoint = _resolve_vpn_endpoint(manager)
        services = manager.get_services_by_dependency(dependency_name)
        rows = [_to_info_row(service, details, vpn_endpoint) for service in services]
        _emit_info_rows(rows, as_json, details, single_item_json=False)
    except Exception as e:
        raise click.ClickException(str(e))


def emit_all_info(ctx: click.Context, as_json: bool, details: bool) -> None:
    manager = get_manager(ctx)
    try:
        vpn_endpoint = _resolve_vpn_endpoint(manager)
        rows = [_to_info_row(service, details, vpn_endpoint) for service in manager.services]
        _emit_info_rows(rows, as_json, details, single_item_json=False)
    except Exception as e:
        raise click.ClickException(str(e))