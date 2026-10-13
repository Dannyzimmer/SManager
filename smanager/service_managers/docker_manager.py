from . import BaseSDV2Manager
from ..datatypes import Service
import os
from ..vpn import VPNService
from ..datatypes import ServiceStatus, SingleStatus
from .registry import register_service_manager


@register_service_manager("docker")
class DockerManager(BaseSDV2Manager):
    def __init__(self, service: Service, vpn: VPNService, restart_delay: int = 5, event_dispatcher=None):
        super().__init__(service, vpn, restart_delay, event_dispatcher=event_dispatcher)

    def _get_compose_file_name(self) -> str | None:
        docker_metadata = self.service.metadata.docker
        if not docker_metadata or not docker_metadata.compose_file:
            return None
        return docker_metadata.compose_file

    def _get_compose_file_path(self) -> str:
        """Returns the path to the docker compose.yml file for this service."""
        compose_file = self._get_compose_file_name()
        if not compose_file:
            raise ValueError(
                f"Service '{self.get_id()}' is configured as docker but is missing "
                "'docker.compose_file'. Provide 'scripts.start' and 'scripts.stop' overrides."
            )
        return os.path.join(self.service.service_abspath, compose_file)

    def _start_runtime(self):
        compose_file = self._get_compose_file_path()
        self.subprocess_run(["docker", "compose", "-f", compose_file, "up", "-d"])

    def _stop_runtime(self):
        compose_file = self._get_compose_file_path()
        self.subprocess_run(["docker", "compose", "-f", compose_file, "down"])

    def _update_docker_commands(self) -> list[list[str]]:
        compose_file = self._get_compose_file_path()
        return [
            ["docker", "compose", "-f", compose_file, "pull", "--ignore-pull-failures"],
            ["docker", "compose", "-f", compose_file, "up", "-d", "--build"],
        ]

    def status(self) -> ServiceStatus:
        """Check the status of all containers in the Docker service and return a
        ServiceStatus object.
        """
        if not self._get_compose_file_name():
            script_status = self._script_status()
            return ServiceStatus(
                id=self.get_id(),
                type=self.service.metadata.runtime.type,
                statuses=[SingleStatus(name="scripts.status", status=script_status or "unknown")],
                enabled=bool(self.service.metadata.active),
            )

        compose_file = self._get_compose_file_path()
        result = self.subprocess_run(
            ["docker", "compose", "-f", compose_file, "ps", "--services", "--filter", "status=running"]
        )
        running_services = set(result.stdout.strip().splitlines())

        all_services_result = self.subprocess_run(
            ["docker", "compose", "-f", compose_file, "config", "--services"]
        )
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
            statuses=service_statuses,
            enabled=bool(self.service.metadata.active),
        )
