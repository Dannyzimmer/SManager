"""
Base class for all simple service managers.
Defines the interface and common functionality for managing a single service.
"""

from abc import abstractmethod
from ..datatypes import ServiceStatus

class BaseManager:
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def start(self):
        """Start the service."""
        raise NotImplementedError("Start method must be implemented by subclasses.")

    @abstractmethod
    def stop(self):
        """Stop the service."""
        raise NotImplementedError("Stop method must be implemented by subclasses.")

    def restart(self):
        """Restart the service."""
        self.stop()
        self.start()

    @abstractmethod
    def status(self)-> ServiceStatus:
        """Check the status of the service."""
        raise NotImplementedError("Status method must be implemented by subclasses.")
    
    @abstractmethod
    def enable(self):
        """Enable the service to be managed (start, stop, restart)."""
        raise NotImplementedError("Enable method must be implemented by subclasses.")
    
    @abstractmethod
    def disable(self):
        """Disable the service from being managed (start, stop, restart)."""
        raise NotImplementedError("Disable method must be implemented by subclasses.")
    
    @abstractmethod
    def get_groups(self):
        """Get the groups associated with this service."""
        raise NotImplementedError("get_groups method must be implemented by subclasses.")
    
    @abstractmethod
    def get_dependencies(self):
        """Get the dependencies of this service."""
        raise NotImplementedError("get_dependencies method must be implemented by subclasses.")
    
    @abstractmethod
    def get_id(self):
        """Get the unique identifier of this service."""
        raise NotImplementedError("get_id method must be implemented by subclasses.")
    
    @abstractmethod
    def is_active(self):
        """Check if the service is active."""
        raise NotImplementedError("is_active method must be implemented by subclasses.")
    