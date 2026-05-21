from ..service_managers import BaseManager, get_service_manager_class
from ..datatypes import Service, GlobalConfig, ServiceStatus, MultiStatus
from ..vpn import VPNService
from . import BaseGlobalManager

class GlobalManager(BaseGlobalManager):
    """GlobalManager is responsible for searching and managing all services found in the 
    specified services directory. It uses the appropriate service manager based on the 
    service metadata.
    """

    def __init__(self, services_root: str, global_config: GlobalConfig, vpn: VPNService):
        super().__init__(services_root, global_config, vpn)

    def _find_service_by_id(self, service_id: str) -> Service:
        """Helper method to find a service by its unique identifier."""
        for service in self.services:
            if service.metadata.id == service_id:
                return service
        raise ValueError(f"Service with ID '{service_id}' not found.")

    def get_service_manager(self, service: Service, restart_delay: int = 5) -> BaseManager:
        """Get the appropriate service manager for the given service based on its metadata."""
        delay = service.metadata.vpn.https_restart_delay if service.metadata.vpn and service.metadata.vpn.https_restart_delay is not None else restart_delay
        manager_class = get_service_manager_class(service.metadata.runtime.type)
        return manager_class(
            service,
            self.vpn,
            restart_delay=delay,
            event_dispatcher=self.event_dispatcher,
        )
        
    def get_group(self, group_name: str) -> list[Service]:
        """Get all services that belong to the specified group."""
        return [s for s in self.services if s.metadata.groups and group_name in s.metadata.groups]
    
    def get_services_by_dependency(self, dependency_name: str) -> list[Service]:
        """Get all services that depend on the specified dependency."""
        return [s for s in self.services if s.metadata.depends_on and dependency_name in s.metadata.depends_on]
    
    def manage_service(self, service_id: str, action: str):
        """Manage a service by performing the specified action (start, stop, restart,
        enable, disable).
        """
        service = self._find_service_by_id(service_id)
        manager = self.get_service_manager(service)
        
        try:
            if action == "start":
                manager.start()
            elif action == "stop":
                manager.stop()
            elif action == "restart":
                manager.restart()
            elif action == "enable":
                manager.enable()
            elif action == "disable":
                manager.disable()
            else:
                raise ValueError(f"Unsupported action: {action}")
        except Exception:
            raise

    def _manage_collection(self, scope: str, identifier: str, services: list[Service], action: str):
        self._emit_event(
            scope=scope,
            action=action,
            phase="before",
            group_name=identifier if scope == "group" else None,
            dependency_name=identifier if scope == "dependency" else None,
            payload={"service_count": len(services)},
        )
        try:
            for service in services:
                self.manage_service(service.metadata.id, action)
        except Exception as exc:
            self._emit_event(
                scope=scope,
                action=action,
                phase="failed",
                group_name=identifier if scope == "group" else None,
                dependency_name=identifier if scope == "dependency" else None,
                payload={"service_count": len(services)},
                error=exc,
            )
            raise
        self._emit_event(
            scope=scope,
            action=action,
            phase="after",
            group_name=identifier if scope == "group" else None,
            dependency_name=identifier if scope == "dependency" else None,
            payload={"service_count": len(services)},
        )
        
    def manage_group(self, group_name: str, action: str):
        """Manage all services in a group by performing the specified action 
        (start, stop, restart, enable, disable).
        """
        services = self.get_group(group_name)
        self._manage_collection("group", group_name, services, action)

    def manage_by_dependency(self, dependency_name: str, action: str):
        """Manage all services that depend on a specific dependency by performing the 
        specified action (start, stop, restart, enable, disable).
        """
        services = self.get_services_by_dependency(dependency_name)
        self._manage_collection("dependency", dependency_name, services, action)
    
    def manage_all(self, action: str):
        """Manage all services by performing the specified action (start, stop, restart, 
        enable, disable)."""
        self._emit_event(
            scope="all",
            action=action,
            phase="before",
            payload={"service_count": len(self.services)},
        )
        try:
            for service in self.services:
                self.manage_service(service.metadata.id, action)
        except Exception as exc:
            self._emit_event(
                scope="all",
                action=action,
                phase="failed",
                payload={"service_count": len(self.services)},
                error=exc,
            )
            raise
        self._emit_event(
            scope="all",
            action=action,
            phase="after",
            payload={"service_count": len(self.services)},
        )
        
    def get_status(self, service_id: str) -> ServiceStatus:
        """Get the status of a specific service by its ID."""
        service = self._find_service_by_id(service_id)
        manager = self.get_service_manager(service)
        result = manager.status()
        result.enabled = bool(service.metadata.active)
        return result
    
    def get_group_status(self, group_name: str) -> MultiStatus:
        """Get the status of all services in a group."""
        services = self.get_group(group_name)
        statuses = [self.get_status(service.metadata.id) for service in services]
        return MultiStatus(services=statuses)
    
    def get_dependency_status(self, dependency_name: str) -> MultiStatus:
        """Get the status of all services that depend on a specific dependency."""
        services = self.get_services_by_dependency(dependency_name)
        statuses = [self.get_status(service.metadata.id) for service in services]
        return MultiStatus(services=statuses)
    
    def get_all_status(self) -> MultiStatus:
        """Get the status of all services."""
        statuses = [self.get_status(service.metadata.id) for service in self.services]
        return MultiStatus(services=statuses)
    
