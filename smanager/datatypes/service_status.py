from dataclasses import dataclass

@dataclass
class SingleStatus:
    name: str
    status: str

@dataclass
class ServiceStatus:
    id: str
    type: str  # e.g. "docker", "local"
    statuses: list[SingleStatus]

@dataclass
class MultiStatus:
    services: list[ServiceStatus]