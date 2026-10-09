"""
The bass manager for SDV2 services.
It extends the BaseManager with SDV2-specific logic, such as handling the SDConfig
file and integrating with VPN services.
"""

import os
import shutil
import socket
import subprocess
import time

from . import BaseManager
from ..datatypes import Service
from ..vpn import VPNService


class BaseSDV2Manager(BaseManager):
    def __init__(self, service: Service, vpn: VPNService, restart_delay: int = 5, event_dispatcher=None):
        super().__init__(service, event_dispatcher=event_dispatcher)
        self.service = service
        self.vpn = vpn
        self.restart_delay = restart_delay

    def enable(self):
        """Change the JSON config to set the service as active."""
        self._emit_event(
            scope="service",
            action="enable",
            phase="before",
            service_id=self.get_id(),
        )
        try:
            self.service.metadata.active = True
            output_path = os.path.join(self.service.service_abspath, self.service.metadata_filename)
            self.service.metadata.write_to_json(output_path)
        except Exception as exc:
            self._emit_event(
                scope="service",
                action="enable",
                phase="failed",
                service_id=self.get_id(),
                error=exc,
            )
            raise
        self._emit_event(
            scope="service",
            action="enable",
            phase="after",
            service_id=self.get_id(),
            payload={"active": True},
        )

    def disable(self):
        """Change the JSON config to set the service as inactive."""
        self._emit_event(
            scope="service",
            action="disable",
            phase="before",
            service_id=self.get_id(),
        )
        try:
            self.service.metadata.active = False
            output_path = os.path.join(self.service.service_abspath, self.service.metadata_filename)
            self.service.metadata.write_to_json(output_path)
        except Exception as exc:
            self._emit_event(
                scope="service",
                action="disable",
                phase="failed",
                service_id=self.get_id(),
                error=exc,
            )
            raise
        self._emit_event(
            scope="service",
            action="disable",
            phase="after",
            service_id=self.get_id(),
            payload={"active": False},
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
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
            if not self._run_script("start"):
                self._start_runtime()
            self._after_runtime_started()
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
            self._ensure_https_stopped()
            if not self._run_script("stop"):
                self._stop_runtime()
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
        """Restart the service.

        A ``scripts.restart`` override fully owns the stop/start sequence; SManager
        still re-establishes the VPN HTTPS serve afterwards. Without an override the
        default is ``stop`` + ``start`` (which honours the start/stop overrides).
        """
        self._emit_event(
            scope="service",
            action="restart",
            phase="before",
            service_id=self.get_id(),
        )
        try:
            if self._run_script("restart"):
                if self._serve_https_enabled():
                    self._wait_for_webui()
                    self._ensure_https_serving()
            else:
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

    # ------------------------------------------------------------------
    # Runtime hooks (implemented by concrete managers)
    # ------------------------------------------------------------------
    def _start_runtime(self):
        raise NotImplementedError("_start_runtime must be implemented by subclasses.")

    def _stop_runtime(self):
        raise NotImplementedError("_stop_runtime must be implemented by subclasses.")

    def _after_runtime_started(self):
        """Ensure the VPN HTTPS serve is active once the runtime has started."""
        if not self._serve_https_enabled():
            return
        self._wait_for_webui()
        self._ensure_https_serving()

    # ------------------------------------------------------------------
    # Scripts
    # ------------------------------------------------------------------
    def _script_value(self, action: str) -> str | None:
        scripts = self.service.metadata.scripts
        if scripts is None:
            return None
        value = getattr(scripts, action, None)
        if value is None or not str(value).strip():
            return None
        return str(value).strip()

    def _resolve_script_path(self, value: str) -> str:
        expanded = os.path.expanduser(value)
        if not os.path.isabs(expanded):
            expanded = os.path.join(self.service.service_abspath, expanded)
        return os.path.abspath(expanded)

    def _run_script(self, action: str) -> bool:
        """Run the configured script for *action*.

        Returns False when no script is configured. Raises a RuntimeError with the
        captured output when the script exits with a non-zero status.
        """
        value = self._script_value(action)
        if value is None:
            return False

        script_path = self._resolve_script_path(value)
        if not os.path.isfile(script_path):
            raise RuntimeError(
                f"Script for '{action}' not found: {script_path}"
            )

        scripts = self.service.metadata.scripts
        interpreter = shutil.which("bash") or shutil.which("sh") or "/bin/sh"

        run_env = os.environ.copy()
        if scripts is not None and scripts.env:
            run_env.update({str(key): str(val) for key, val in scripts.env.items()})

        cwd = self.service.service_abspath
        if scripts is not None and scripts.working_dir:
            candidate = os.path.expanduser(scripts.working_dir)
            if not os.path.isabs(candidate):
                candidate = os.path.join(self.service.service_abspath, candidate)
            cwd = candidate

        try:
            subprocess.run(
                [interpreter, script_path],
                capture_output=True,
                text=True,
                check=True,
                cwd=cwd,
                env=run_env,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise RuntimeError(
                f"Script '{action}' failed for service '{self.get_id()}' "
                f"({script_path}): {detail or f'exit code {exc.returncode}'}"
            ) from exc

        return True

    def _script_status(self) -> str | None:
        """Return the status reported by a ``scripts.status`` override.

        Returns None when no status script is configured. The exit code drives the
        result: 0 -> "running", anything else -> "stopped", unusable -> "unknown".
        """
        value = self._script_value("status")
        if value is None:
            return None

        script_path = self._resolve_script_path(value)
        if not os.path.isfile(script_path):
            return "unknown"

        scripts = self.service.metadata.scripts
        interpreter = shutil.which("bash") or shutil.which("sh") or "/bin/sh"

        run_env = os.environ.copy()
        if scripts is not None and scripts.env:
            run_env.update({str(key): str(val) for key, val in scripts.env.items()})

        cwd = self.service.service_abspath
        if scripts is not None and scripts.working_dir:
            candidate = os.path.expanduser(scripts.working_dir)
            if not os.path.isabs(candidate):
                candidate = os.path.join(self.service.service_abspath, candidate)
            cwd = candidate

        try:
            result = subprocess.run(
                [interpreter, script_path],
                capture_output=True,
                text=True,
                check=False,
                cwd=cwd,
                env=run_env,
            )
        except OSError:
            return "unknown"

        return "running" if result.returncode == 0 else "stopped"

    # ------------------------------------------------------------------
    # VPN / HTTPS helpers
    # ------------------------------------------------------------------
    def _serve_https_enabled(self) -> bool:
        vpn = self.service.metadata.vpn
        return bool(vpn and vpn.serve_https)

    def _webui_port(self) -> int:
        return int(self.service.metadata.runtime.ports.webui)

    def _ensure_https_serving(self) -> None:
        if not self._serve_https_enabled():
            return
        port = self._webui_port()
        try:
            if not self.vpn.is_connected():
                self.vpn.connect()
            self.vpn.serve_https(port)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to serve HTTPS on port {port} via VPN: {exc}"
            ) from exc

    def _ensure_https_stopped(self) -> None:
        if not self._serve_https_enabled():
            return
        port = self._webui_port()
        try:
            self.vpn.stop_serving_https(port)
        except Exception:
            # Stopping the service must not fail because the VPN endpoint was
            # not being served or the VPN is unreachable.
            pass

    def _wait_for_webui(self) -> bool:
        """Wait until the WebUI port accepts connections (best effort)."""
        return self._wait_for_port(self._webui_port(), self.restart_delay)

    def _wait_for_port(self, port: int, timeout: float | None = None) -> bool:
        timeout = self.restart_delay if timeout is None else timeout
        deadline = time.monotonic() + max(float(timeout), 0.0)
        while time.monotonic() < deadline:
            if self._port_is_open(port):
                return True
            time.sleep(0.5)
        return False

    @staticmethod
    def _port_is_open(port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                return sock.connect_ex(("127.0.0.1", int(port))) == 0
        except OSError:
            return False

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------
    def get_groups(self):
        """Get the groups associated with this service."""
        return self.service.metadata.groups

    def get_dependencies(self):
        """Get the dependencies of this service."""
        return self.service.metadata.depends_on

    def get_id(self):
        """Get the unique identifier of this service."""
        return self.service.metadata.id

    def is_active(self):
        """Check if the service is active."""
        return self.service.metadata.active
