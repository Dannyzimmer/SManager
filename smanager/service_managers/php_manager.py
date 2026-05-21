from __future__ import annotations

import os
import shlex
import subprocess
from urllib import error as urlerror
from urllib import request as urlrequest

from . import BaseSDV2Manager
from .registry import register_service_manager
from ..datatypes import Service, ServiceStatus, SingleStatus
from ..vpn import VPNService


@register_service_manager("php")
class PhpManager(BaseSDV2Manager):
    def __init__(self, service: Service, vpn: VPNService, restart_delay: int = 5, event_dispatcher=None):
        super().__init__(service, vpn, restart_delay, event_dispatcher=event_dispatcher)

    def _php_metadata(self):
        php_metadata = self.service.metadata.php
        if php_metadata is None:
            raise ValueError(
                f"Service '{self.get_id()}' is configured as php but is missing 'php' section."
            )
        return php_metadata

    def _run_shell_command(self, command: str) -> subprocess.CompletedProcess:
        php_metadata = self._php_metadata()
        command_args = shlex.split(command)

        run_env = os.environ.copy()
        if php_metadata.env:
            run_env.update({str(key): str(value) for key, value in php_metadata.env.items()})

        cwd = php_metadata.working_dir or self.service.service_abspath
        return subprocess.run(
            command_args,
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
            env=run_env,
        )

    def _run_status_command(self, command: str) -> subprocess.CompletedProcess:
        php_metadata = self._php_metadata()
        command_args = shlex.split(command)

        run_env = os.environ.copy()
        if php_metadata.env:
            run_env.update({str(key): str(value) for key, value in php_metadata.env.items()})

        cwd = php_metadata.working_dir or self.service.service_abspath
        return subprocess.run(
            command_args,
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd,
            env=run_env,
        )

    def start(self):
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
            return

        try:
            self._run_shell_command(self._php_metadata().start_command)
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
        self._emit_event(
            scope="service",
            action="stop",
            phase="before",
            service_id=self.get_id(),
        )

        try:
            self._run_shell_command(self._php_metadata().stop_command)
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
        self._emit_event(
            scope="service",
            action="restart",
            phase="before",
            service_id=self.get_id(),
        )

        try:
            try:
                self.stop()
            except Exception:
                pass
            self.start()
        except Exception as exc:
            self._emit_event(
                scope="service",
                action="restart",
                phase="failed",
                service_id=self.get_id(),
                error=exc,
            )
            raise

        self._emit_event(
            scope="service",
            action="restart",
            phase="after",
            service_id=self.get_id(),
        )

    def status(self) -> ServiceStatus:
        php_metadata = self._php_metadata()
        status_command = php_metadata.status_command

        if status_command:
            result = self._run_status_command(status_command)
            status = "running" if result.returncode == 0 else "stopped"
            return ServiceStatus(
                id=self.get_id(),
                type=self.service.metadata.runtime.type,
                statuses=[SingleStatus(name="status_command", status=status)],
                enabled=bool(self.service.metadata.active),
            )

        healthcheck_url = php_metadata.healthcheck_url

        if not healthcheck_url:
            return ServiceStatus(
                id=self.get_id(),
                type=self.service.metadata.runtime.type,
                statuses=[SingleStatus(name="healthcheck", status="unknown")],
                enabled=bool(self.service.metadata.active),
            )

        timeout = php_metadata.healthcheck_timeout
        request = urlrequest.Request(healthcheck_url, method="GET")

        try:
            with urlrequest.urlopen(request, timeout=timeout) as response:
                code = int(getattr(response, "status", 0) or response.getcode())
            if 200 <= code < 400:
                status = "running"
            elif 400 <= code < 600:
                status = "error"
            else:
                status = "error"
        except urlerror.HTTPError as exc:
            if 400 <= exc.code < 600:
                status = "error"
            else:
                status = "stopped"
        except (urlerror.URLError, TimeoutError):
            status = "stopped"

        return ServiceStatus(
            id=self.get_id(),
            type=self.service.metadata.runtime.type,
            statuses=[SingleStatus(name=healthcheck_url, status=status)],
            enabled=bool(self.service.metadata.active),
        )
