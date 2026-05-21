"""Registry for service manager implementations."""

from __future__ import annotations

from typing import Dict, Type

from .base_manager import BaseManager


_SERVICE_MANAGER_REGISTRY: Dict[str, Type[BaseManager]] = {}


def register_service_manager(runtime_type: str):
    """Decorator to register a service manager class by runtime type."""

    def decorator(cls: Type[BaseManager]):
        if runtime_type in _SERVICE_MANAGER_REGISTRY:
            raise ValueError(
                f"Service manager for runtime type '{runtime_type}' is already registered."
            )
        _SERVICE_MANAGER_REGISTRY[runtime_type] = cls
        return cls

    return decorator


def get_service_manager_class(runtime_type: str) -> Type[BaseManager]:
    """Return a registered service manager class for runtime_type."""
    if runtime_type not in _SERVICE_MANAGER_REGISTRY:
        raise ValueError(f"Unsupported runtime type: {runtime_type}")
    return _SERVICE_MANAGER_REGISTRY[runtime_type]


def list_service_managers() -> list[str]:
    """Return registered runtime types."""
    return list(_SERVICE_MANAGER_REGISTRY.keys())
