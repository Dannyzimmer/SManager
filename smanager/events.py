"""
Lightweight event primitives for manager lifecycle callbacks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Callable, Optional


logger = logging.getLogger(__name__)


@dataclass
class ManagerEvent:
    """Represents a lifecycle event emitted by a manager."""

    name: str
    scope: str
    action: str
    phase: str
    source: str
    service_id: Optional[str] = None
    group_name: Optional[str] = None
    dependency_name: Optional[str] = None
    message: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)
    error: Optional[BaseException] = None

    def to_dict(self) -> dict[str, Any]:
        """Return a stable, JSON-friendly representation of this event."""
        return {
            "name": self.name,
            "scope": self.scope,
            "action": self.action,
            "phase": self.phase,
            "source": self.source,
            "service_id": self.service_id,
            "group_name": self.group_name,
            "dependency_name": self.dependency_name,
            "message": self.message,
            "payload": self.payload,
            "error": self._serialize_error(),
        }

    def _serialize_error(self) -> dict[str, str] | None:
        if self.error is None:
            return None
        return {
            "type": self.error.__class__.__name__,
            "message": str(self.error),
        }


EventCallback = Callable[[ManagerEvent], None]


class ManagerEventDispatcher:
    """Small synchronous dispatcher for manager events.

    Callbacks are isolated from one another so that a failing observer does not
    break the manager operation that emitted the event.
    """

    def __init__(self) -> None:
        self._listeners: list[tuple[Optional[str], EventCallback]] = []

    def on(self, callback: EventCallback, event_name: str | None = None) -> None:
        """Register a callback for all events or for a specific event name."""
        self._listeners.append((event_name, callback))

    def off(self, callback: EventCallback, event_name: str | None = None) -> None:
        """Unregister a callback."""
        self._listeners = [
            (registered_event_name, registered_callback)
            for registered_event_name, registered_callback in self._listeners
            if not (
                registered_callback is callback
                and registered_event_name == event_name
            )
        ]

    def emit(self, event: ManagerEvent) -> None:
        """Dispatch an event to all matching listeners."""
        for registered_event_name, callback in list(self._listeners):
            if registered_event_name not in (None, "*", event.name):
                continue
            try:
                callback(event)
            except Exception:  # pragma: no cover - defensive logging path
                logger.exception(
                    "Callback failure while handling event %s", event.name
                )
