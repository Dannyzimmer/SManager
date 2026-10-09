from . import BaseSDV2Manager
from ..datatypes import Service
from ..vpn import VPNService
import subprocess
from ..datatypes import ServiceStatus, SingleStatus
from .registry import register_service_manager


@register_service_manager("local")
class LocalManager(BaseSDV2Manager):
    def __init__(self, service: Service, vpn: VPNService, restart_delay: int = 5, event_dispatcher=None):
        super().__init__(service, vpn, restart_delay, event_dispatcher=event_dispatcher)

    def _get_systemd_services(self) -> list[str]:
        local_metadata = self.service.metadata.local
        if not local_metadata or not local_metadata.systemd_services:
            raise ValueError(
                f"Service '{self.get_id()}' is configured as local but is missing "
                "'local.systemd_services'. Provide 'scripts.start' and 'scripts.stop' "
                "overrides or define the systemd services."
            )
        return local_metadata.systemd_services

    def _start_runtime(self):
        for service_name in self._get_systemd_services():
            self.subprocess_run(["systemctl", "start", service_name])

    def _stop_runtime(self):
        for service_name in self._get_systemd_services():
            self.subprocess_run(["systemctl", "stop", service_name])

    def status(self) -> ServiceStatus:
        """Check the status of the local systemd service and return a ServiceStatus object."""
        script_status = self._script_status()
        if script_status is not None:
            return ServiceStatus(
                id=self.get_id(),
                type=self.service.metadata.runtime.type,
                statuses=[SingleStatus(name="scripts.status", status=script_status)],
                enabled=bool(self.service.metadata.active),
            )

        service_statuses = []
        for service_name in self._get_systemd_services():
            result = subprocess.run(
                ["systemctl", "is-active", service_name],
                capture_output=True,
                text=True,
                check=False,
            )
            status_text = result.stdout.strip() or result.stderr.strip()
            if not status_text:
                status_text = "active" if result.returncode == 0 else "inactive"
            status = SingleStatus(
                name=service_name,
                status=status_text
            )
            service_statuses.append(status)
        return ServiceStatus(
            id=self.get_id(), 
            type=self.service.metadata.runtime.type,
            statuses=service_statuses,
            enabled=bool(self.service.metadata.active),
        )
