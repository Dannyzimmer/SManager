from dataclasses import dataclass
from typing import Optional


@dataclass
class SingleStatus:
    name: str
    status: str


@dataclass
class UpdateInfo:
    """Result of checking whether a newer version of a service is available.

    ``available`` is ``True``/``False`` when it could be determined, or ``None``
    when it is unknown (no current version, offline, unsupported, ...).
    """

    available: Optional[bool] = None
    current: Optional[str] = None
    latest: Optional[str] = None
    source: Optional[str] = None
    error: Optional[str] = None
    # Nature of the current/latest values: "version", "tag" or "digest".
    current_kind: Optional[str] = None
    latest_kind: Optional[str] = None
    # Digests backing the comparison, kept even when a human version is shown.
    current_digest: Optional[str] = None
    latest_digest: Optional[str] = None


@dataclass
class ServiceStatus:
    id: str
    type: str  # e.g. "docker", "local"
    statuses: list[SingleStatus]
    enabled: bool = True
    update: Optional[UpdateInfo] = None


@dataclass
class MultiStatus:
    services: list[ServiceStatus]