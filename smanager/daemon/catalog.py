"""Service catalog for the daemon.

Wraps the existing ``GlobalManager`` discovery so the daemon caches the
catalog instead of re-crawling on every request.
"""

from __future__ import annotations

from typing import Any

from ..datatypes import Service


class Catalog:
    def __init__(self, manager):
        self._manager = manager

    def services(self) -> list[Service]:
        return self._manager.services

    def get(self, service_id: str) -> Service:
        return self._manager.get_service(service_id)

    def reload(self) -> int:
        self._manager.services = self._manager.discover_services()
        return len(self._manager.services)

    def list_summary(self) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        for service in self.services():
            metadata = service.metadata
            summary.append(
                {
                    "id": metadata.id,
                    "name": metadata.name,
                    "description": metadata.description,
                    "runtime": metadata.runtime.type,
                    "active": bool(metadata.active),
                    "groups": list(metadata.groups or []),
                    "path": str(service.service_abspath),
                }
            )
        return summary
