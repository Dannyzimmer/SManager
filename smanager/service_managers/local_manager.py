from . import BaseSDV2Manager
from ..datatypes import Service
from ..vpn import VPNService
import time
import subprocess
from ..datatypes import ServiceStatus, SingleStatus

class LocalManager(BaseSDV2Manager):
    def __init__(self, service: Service, vpn: VPNService, restart_delay: int = 5, event_dispatcher=None):
        super().__init__(service, vpn, restart_delay, event_dispatcher=event_dispatcher)

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
            for service_name in self._get_systemd_services():
                self.subprocess_run(["systemctl", "start", service_name])
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
        """Stop the local systemd service."""
        self._emit_event(
            scope="service",
            action="stop",
            phase="before",
            service_id=self.get_id(),
        )
        try:
            for service_name in self._get_systemd_services():
                self.subprocess_run(["systemctl", "stop", service_name])
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
        """Restart the local systemd service."""
        self._emit_event(
            scope="service",
            action="restart",
            phase="before",
            service_id=self.get_id(),
        )
        self.stop()
        self.vpn.stop_serving_https(self.service.metadata.runtime.ports.webui)
        self.start()
        time.sleep(self.restart_delay)
        self.vpn.serve_https(self.service.metadata.runtime.ports.webui)
        self._emit_event(
            scope="service",
            action="restart",
            phase="after",
            service_id=self.get_id(),
            payload={"serve_https": True},
        )
    
    def status(self)-> ServiceStatus:
        """Check the status of the local systemd service and return a ServiceStatus object."""
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
