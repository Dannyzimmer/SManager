from . import BaseSDV2Manager
from ..datatypes import Service
import os
from ..vpn import VPNService
import time
from ..datatypes import ServiceStatus, SingleStatus

class DockerManager(BaseSDV2Manager):
    def __init__(self, service: Service, vpn: VPNService, restart_delay: int = 5):
        super().__init__(service, vpn, restart_delay)

    def _get_compose_file_name(self) -> str:
        docker_metadata = self.service.metadata.docker
        if not docker_metadata or not docker_metadata.compose_file:
            raise ValueError(
                f"Service '{self.get_id()}' is configured as docker but is missing "
                "'docker.compose_file'."
            )
        return docker_metadata.compose_file

    def _get_compose_file_path(self) -> str:
        """Returns the path to the docker compose.yml file for this service."""
        return os.path.join(
            self.service.service_abspath, 
            self._get_compose_file_name()
            )
    
    def start(self):
        """Start the Docker service using docker compose."""
        compose_file = self._get_compose_file_path()
        self.subprocess_run(["docker", "compose", "-f", compose_file, "up", "-d"])

    def stop(self):
        """Stop the Docker service using docker compose."""
        compose_file = self._get_compose_file_path()
        self.subprocess_run(["docker", "compose", "-f", compose_file, "down"])

    def restart(self):
        """Restart the Docker service using docker compose."""
        serve_https = self.service.metadata.vpn and self.service.metadata.vpn.serve_https
        try:
            self.stop()
        except:
            pass # Ignore errors during stop, we will try to start anyway
        if serve_https:
            try:
                self.vpn.stop_serving_https(self.service.metadata.runtime.ports.webui)
            except:
                pass # Ignore errors during VPN stop, we will try to start anyway
        self.start()
        time.sleep(self.restart_delay)
        if serve_https:
            self.vpn.serve_https(self.service.metadata.runtime.ports.webui)

    def status(self)-> ServiceStatus:
        """Check the status of all containers in the Docker service and return a
        ServiceStatus object.
        """
        compose_file = self._get_compose_file_path()
        result = self.subprocess_run(["docker", "compose", "-f", compose_file, "ps", "--services", "--filter", "status=running"])
        running_services = set(result.stdout.strip().splitlines())
        
        all_services_result = self.subprocess_run(["docker", "compose", "-f", compose_file, "config", "--services"])
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
            statuses=service_statuses
        )
    