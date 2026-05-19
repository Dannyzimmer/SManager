"""
This module implements a registry for VPN providers.
It allows for dynamic registration and retrieval of VPN provider classes by name.
"""
from . import VPNService
from typing import Dict, Type

# Global registry for VPN providers
_VPN_REGISTRY: Dict[str, Type[VPNService]] = {}

def register_vpn(name: str):
    """Decorator to register a model class with a given name."""
    def decorator(cls: Type[VPNService]):
        if name in _VPN_REGISTRY:
            raise ValueError(f"VPN provider \"{name}\" is already registered.")
        _VPN_REGISTRY[name] = cls
        return cls
    return decorator

def get_vpn(name: str) -> Type[VPNService]:
    """Retrieves a VPN provider class by name."""
    if name not in _VPN_REGISTRY:
        raise ValueError(f"VPN provider \"{name}\" is not registered.")
    return _VPN_REGISTRY[name]

def list_vpns() -> list[str]:
    """Returns a list of registered VPN provider names."""
    return list(_VPN_REGISTRY.keys())