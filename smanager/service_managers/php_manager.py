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

    def _start_runtime(self):
        start_command = self._php_metadata().start_command
        if not start_command or not str(start_command).strip():
            raise ValueError(
                f"Service '{self.get_id()}' is configured as php but is missing "
                "'php.start_command'. Provide 'scripts.start' or define the command."
            )
        self._run_shell_command(start_command)

    def _stop_runtime(self):
        stop_command = self._php_metadata().stop_command
        if not stop_command or not str(stop_command).strip():
            raise ValueError(
                f"Service '{self.get_id()}' is configured as php but is missing "
                "'php.stop_command'. Provide 'scripts.stop' or define the command."
            )
        self._run_shell_command(stop_command)

    def status(self) -> ServiceStatus:
        script_status = self._script_status()
        if script_status is not None:
            return ServiceStatus(
                id=self.get_id(),
                type=self.service.metadata.runtime.type,
                statuses=[SingleStatus(name="scripts.status", status=script_status)],
                enabled=bool(self.service.metadata.active),
            )

        php_metadata = self.service.metadata.php
        if php_metadata is None:
            return ServiceStatus(
                id=self.get_id(),
                type=self.service.metadata.runtime.type,
                statuses=[SingleStatus(name="scripts.status", status="unknown")],
                enabled=bool(self.service.metadata.active),
            )
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
