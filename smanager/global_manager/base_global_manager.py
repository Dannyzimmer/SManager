from ..service_managers import BaseManager
from ..datatypes import Service, GlobalConfig, ServiceStatus, MultiStatus
from ..crawler import ServiceDiscoverer
from ..vpn import VPNService
from abc import abstractmethod

class BaseGlobalManager:
    """BaseGlobalManager is an abstract class that defines the interface for a global manager.
    It provides methods for searching and managing services, but does not implement the
    actual logic. Subclasses should implement the specific logic for managing services.
    """

    def __init__(self, services_dir: str, global_config: GlobalConfig, vpn: VPNService):
        self.services_dir = services_dir
        self.global_config = global_config
        self.vpn = vpn
        self.crawler = ServiceDiscoverer(services_dir)
        self.services = self.discover_services()

    def discover_services(self) -> list[Service]:
        """Discover services in the specified services directory."""
        return self.crawler.discover_services()
    
    @abstractmethod
    def get_service_manager(self, service: Service) -> BaseManager:
        """Get the appropriate service manager for the given service."""
        raise NotImplementedError("get_service_manager method must be implemented by subclasses.")
    
    @abstractmethod
    def get_group(self, group_name: str) -> list[Service]:
        """Get all services that belong to the specified group."""
        raise NotImplementedError("get_group method must be implemented by subclasses.")
    
    @abstractmethod
    def get_services_by_dependency(self, dependency_name: str) -> list[Service]:
        """Get all services that depend on the specified dependency."""
        raise NotImplementedError("get_services_by_dependency method must be implemented by subclasses.")
    
    @abstractmethod
    def manage_service(self, service_id: str, action: str):
        """Manage a service by performing the specified action (start, stop, restart, enable, disable)."""
        raise NotImplementedError("manage_service method must be implemented by subclasses.")
    
    @abstractmethod
    def manage_group(self, group_name: str, action: str):
        """Manage all services in a group by performing the specified action 
        (start, stop, restart).
        """
        raise NotImplementedError("manage_group method must be implemented by subclasses.")
    
    @abstractmethod
    def manage_by_dependency(self, dependency_name: str, action: str):
        """Manage all services that depend on a specific dependency by performing the 
        specified action (start, stop, restart, enable, disable).
        """
        raise NotImplementedError("manage_by_dependency method must be implemented by subclasses.")
    
    @abstractmethod
    def manage_all(self, action: str):
        """Manage all services by performing the specified action (start, stop, restart, enable, disable)."""
        raise NotImplementedError("manage_all method must be implemented by subclasses.")

    @abstractmethod
    def get_status(self, service_id: str) -> ServiceStatus:
        """Get the status of a specific service by its ID."""
        raise NotImplementedError("get_status method must be implemented by subclasses.")
    
    @abstractmethod
    def get_group_status(self, group_name: str) -> MultiStatus:
        """Get the status of all services in a group."""
        raise NotImplementedError("get_group_status method must be implemented by subclasses.")
    
    @abstractmethod
    def get_dependency_status(self, dependency_name: str) -> MultiStatus:
        """Get the status of all services that depend on a specific dependency."""
        raise NotImplementedError("get_dependency_status method must be implemented by subclasses.")
    
    @abstractmethod
    def get_all_status(self) -> MultiStatus:
        """Get the status of all services."""
        raise NotImplementedError("get_all_status method must be implemented by subclasses.")