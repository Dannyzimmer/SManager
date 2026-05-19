from . import BaseSDV2Manager
from ..datatypes import Service
import subprocess
from ..vpn import VPNService
import time
from ..datatypes import ServiceStatus, SingleStatus

class LocalManager(BaseSDV2Manager):
    def __init__(self, service: Service, vpn: VPNService, restart_delay: int = 5):
        super().__init__()

    def start(self):
        """Start the local systemd service."""
        for service_name in self.service.metadata.local.systemd_services:
            subprocess.run(["systemctl", "start", service_name], check=True)
    
    def stop(self):
        """Stop the local systemd service."""
        for service_name in self.service.metadata.local.systemd_services:
            subprocess.run(["systemctl", "stop", service_name], check=True)

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
        for service_name in self.service.metadata.local.systemd_services:
            result = subprocess.run(["systemctl", "is-active", service_name], capture_output=True, text=True)
            status = SingleStatus(
                name=service_name,
                status=result.stdout.strip()
            )
            service_statuses.append(status)
        return ServiceStatus(
            id=self.get_id(), 
            type=self.service.metadata.runtime.type,
            services=service_statuses
        )
