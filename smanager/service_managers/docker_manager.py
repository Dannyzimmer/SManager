from . import BaseSDV2Manager
from ..datatypes import Service
import os
from ..vpn import VPNService
import time
from ..datatypes import ServiceStatus, SingleStatus

class DockerManager(BaseSDV2Manager):
    def __init__(self, service: Service, vpn: VPNService, restart_delay: int = 5, event_dispatcher=None):
        super().__init__(service, vpn, restart_delay, event_dispatcher=event_dispatcher)

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
        self._emit_event(
            scope="service",
            action="start",
            phase="before",
            service_id=self.get_id(),
        )
        if not self.service.metadata.active:
            self._emit_event(
                scope="service",
                action="start",
                phase="skipped",
                service_id=self.get_id(),
                message="Service is inactive.",
            )
            return # Don't start if the service is not active
        try:
            compose_file = self._get_compose_file_path()
            self.subprocess_run(["docker", "compose", "-f", compose_file, "up", "-d"])
        except Exception as exc:
            self._emit_event(
                scope="service",
                action="start",
                phase="failed",
                service_id=self.get_id(),
                error=exc,
            )
            raise
        self._emit_event(
            scope="service",
            action="start",
            phase="after",
            service_id=self.get_id(),
        )

    def stop(self):
        """Stop the Docker service using docker compose."""
        self._emit_event(
            scope="service",
            action="stop",
            phase="before",
            service_id=self.get_id(),
        )
        try:
            compose_file = self._get_compose_file_path()
            self.subprocess_run(["docker", "compose", "-f", compose_file, "down"])
        except Exception as exc:
            self._emit_event(
                scope="service",
                action="stop",
                phase="failed",
                service_id=self.get_id(),
                error=exc,
            )
            raise
        self._emit_event(
            scope="service",
            action="stop",
            phase="after",
            service_id=self.get_id(),
        )

    def restart(self):
        """Restart the Docker service using docker compose."""
        self._emit_event(
            scope="service",
            action="restart",
            phase="before",
            service_id=self.get_id(),
        )
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
        self._emit_event(
            scope="service",
            action="restart",
            phase="after",
            service_id=self.get_id(),
            payload={"serve_https": bool(serve_https)},
        )

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
    