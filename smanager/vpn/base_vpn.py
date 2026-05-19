"""
Defines the base VPN service interface that all VPN implementations must follow.
"""
from abc import ABC, abstractmethod

class VPNService:

    @abstractmethod
    def connect(self):
        """Connect to the VPN."""
        raise NotImplementedError("Connect method must be implemented by subclasses.")

    @abstractmethod
    def disconnect(self):
        """Disconnect from the VPN."""
        raise NotImplementedError("Disconnect method must be implemented by subclasses.")

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the VPN is currently connected."""
        raise NotImplementedError("is_connected method must be implemented by subclasses.")
    
    @abstractmethod
    def serve_https(self, port: int):
        """Serve the VPN connection over HTTPS on the specified port."""
        raise NotImplementedError("serve_https method must be implemented by subclasses.")
    
    @abstractmethod
    def stop_serving_https(self, port: int):
        """Stop serving the VPN connection over HTTPS on the specified port."""
        raise NotImplementedError("stop_serving_https method must be implemented by subclasses.")
    
