from . import BaseSDV2Manager
from ..datatypes import Service
import subprocess
import os
from ..vpn import VPNService
import time
from ..datatypes import ServiceStatus, SingleStatus

class DockerManager(BaseSDV2Manager):
    def __init__(self, service: Service, vpn: VPNService, restart_delay: int = 5):
        super().__init__()
        self._compose_path = self.service.metadata.docker.compose_file

    def _get_compose_file_path(self) -> str:
        """Returns the path to the docker-compose.yml file for this service."""
        return os.path.join(
            self.service.service_abspath, 
            self.service.metadata.docker.compose_file
            )
    
    def start(self):
        """Start the Docker service using docker-compose."""
        compose_file = self._get_compose_file_path()
        subprocess.run(["docker-compose", "-f", compose_file, "up", "-d"], check=True)

    def stop(self):
        """Stop the Docker service using docker-compose."""
        compose_file = self._get_compose_file_path()
        subprocess.run(["docker-compose", "-f", compose_file, "down"], check=True)

    def restart(self):
        """Restart the Docker service using docker-compose."""
        self.stop()
        self.vpn.stop_serving_https(self.service.metadata.runtime.ports.webui)
        self.start()
        time.sleep(self.restart_delay)
        self.vpn.serve_https(self.service.metadata.runtime.ports.webui)

    def status(self)-> ServiceStatus:
        """Check the status of all containers in the Docker service and return a
        ServiceStatus object.
        """
        compose_file = self._get_compose_file_path()
        result = subprocess.run(["docker-compose", "-f", compose_file, "ps", "--services", "--filter", "status=running"], capture_output=True, text=True)
        running_services = set(result.stdout.strip().splitlines())
        
        all_services_result = subprocess.run(["docker-compose", "-f", compose_file, "config", "--services"], capture_output=True, text=True)
        all_services = set(all_services_result.stdout.strip().splitlines())
        
        service_statuses = []
        for service_name in all_services:
            status = SingleStatus(
                name=service_name,
                status="running" if service_name in running_services else "stopped"
            )
            service_statuses.append(status)
        
        return ServiceStatus(
            id=self.get_id(), 
            type=self.service.metadata.runtime.type,
            services=service_statuses
        )
    