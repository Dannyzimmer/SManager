"""
Implements the Tailscale VPN service.
"""

from .. import VPNService
from ..registry import register_vpn
import subprocess
import json

@register_vpn("tailscale")
class TailscaleVPN(VPNService):
    def __init__(self):
        self.connected = self.is_connected()

    def connect(self):
        """Connect to the Tailscale VPN."""
        try:
            subprocess.run(["sudo", "tailscale", "up"], check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError("Failed to connect to Tailscale VPN") from e
        self.connected = self.is_connected()

    def disconnect(self):
        """Disconnect from the Tailscale VPN."""
        try:
            subprocess.run(["sudo", "tailscale", "down"], check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError("Failed to disconnect from Tailscale VPN") from e
        self.connected = self.is_connected()

    def is_connected(self) -> bool:
        """Check if the VPN is currently connected."""
        try:
            status = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, check=True)
            return json.loads(status.stdout).get("BackendState", "") == "Running"
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
            return False

    def serve_https(self, port: int):
        """Serve the VPN connection over HTTPS on the specified port."""
        try:
            subprocess.run(["sudo", "tailscale", "serve", "--bg", f"--https={port}", f"http://localhost:{port}"], check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to serve HTTPS on port {port} via Tailscale") from e
    
    def stop_serving_https(self, port: int):
        """Stop serving the VPN connection over HTTPS on the specified port."""
        try:
            subprocess.run(["sudo", "tailscale", "serve", f"--https={port}", "off"], check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to stop serving HTTPS on port {port} via Tailscale") from e