from . import BaseSDV2Manager
from ..datatypes import Service
from ..vpn import VPNService
import time
from ..datatypes import ServiceStatus, SingleStatus

class LocalManager(BaseSDV2Manager):
    def __init__(self, service: Service, vpn: VPNService, restart_delay: int = 5):
        super().__init__(service, vpn, restart_delay)

    def _get_systemd_services(self) -> list[str]:
        local_metadata = self.service.metadata.local
        if not local_metadata or not local_metadata.systemd_services:
            raise ValueError(
                f"Service '{self.get_id()}' is configured as local but is missing "
                "'local.systemd_services'."
            )
        return local_metadata.systemd_services

    def start(self):
        """Start the local systemd service."""
        for service_name in self._get_systemd_services():
            self.subprocess_run(["systemctl", "start", service_name])
    
    def stop(self):
        """Stop the local systemd service."""
        for service_name in self._get_systemd_services():
            self.subprocess_run(["systemctl", "stop", service_name])

    def restart(self):
        """Restart the local systemd service."""
        self.stop()
        self.vpn.stop_serving_https(self.service.metadata.runtime.ports.webui)
        self.start()
        time.sleep(self.restart_delay)
        self.vpn.serve_https(self.service.metadata.runtime.ports.webui)
    
    def status(self)-> ServiceStatus:
        """Check the status of the local systemd service and return a ServiceStatus object."""
        service_statuses = []
        for service_name in self._get_systemd_services():
            result = self.subprocess_run(["systemctl", "is-active", service_name])
            status = SingleStatus(
                name=service_name,
                status=result.stdout.strip()
            )
            service_statuses.append(status)
        return ServiceStatus(
            id=self.get_id(), 
            type=self.service.metadata.runtime.type,
            statuses=service_statuses
        )
