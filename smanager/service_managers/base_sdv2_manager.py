"""
The bass manager for SDV2 services.
It extends the BaseManager with SDV2-specific logic, such as handling the SDConfig
file and integrating with VPN services.
"""

from . import BaseManager
from ..datatypes import Service
from ..vpn import VPNService
import os

class BaseSDV2Manager(BaseManager):
    def __init__(self, service: Service, vpn: VPNService, restart_delay: int = 5, event_dispatcher=None):
        super().__init__(service, event_dispatcher=event_dispatcher)
        self.service = service
        self.vpn = vpn
        self.restart_delay = restart_delay

    def enable(self):
        """Change the JSON config to set the service as active."""
        self._emit_event(
            scope="service",
            action="enable",
            phase="before",
            service_id=self.get_id(),
        )
        try:
            self.service.metadata.active = True
            output_path = os.path.join(self.service.service_abspath, self.service.metadata_filename)
            self.service.metadata.write_to_json(output_path)
        except Exception as exc:
            self._emit_event(
                scope="service",
                action="enable",
                phase="failed",
                service_id=self.get_id(),
                error=exc,
            )
            raise
        self._emit_event(
            scope="service",
            action="enable",
            phase="after",
            service_id=self.get_id(),
            payload={"active": True},
        )

    def disable(self):
        """Change the JSON config to set the service as inactive."""
        self._emit_event(
            scope="service",
            action="disable",
            phase="before",
            service_id=self.get_id(),
        )
        try:
            self.service.metadata.active = False
            output_path = os.path.join(self.service.service_abspath, self.service.metadata_filename)
            self.service.metadata.write_to_json(output_path)
        except Exception as exc:
            self._emit_event(
                scope="service",
                action="disable",
                phase="failed",
                service_id=self.get_id(),
                error=exc,
            )
            raise
        self._emit_event(
            scope="service",
            action="disable",
            phase="after",
            service_id=self.get_id(),
            payload={"active": False},
        )

    def get_groups(self):
        """Get the groups associated with this service."""
        return self.service.metadata.groups
    
    def get_dependencies(self):
        """Get the dependencies of this service."""
        return self.service.metadata.depends_on
    
    def get_id(self):
        """Get the unique identifier of this service."""
        return self.service.metadata.id
    
    def is_active(self):
        """Check if the service is active."""
        return self.service.metadata.active