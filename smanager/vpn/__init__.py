from .base_vpn import VPNService
from .registry import register_vpn, get_vpn, list_vpns
from .providers import TailscaleVPN

__all__ = [
    "VPNService",
    "register_vpn",
    "get_vpn",
    "list_vpns",
    "TailscaleVPN"
]