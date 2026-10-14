"""Install/uninstall helpers for the system daemon.

This module only *generates* artifacts and (optionally) runs the system
commands; it never runs during ``pip install``. The CLI layer asks for root
explicitly and refuses otherwise.

All filesystem paths are relative to a configurable ``root`` (default ``/``) and
all system commands go through an injectable runner, so the logic is fully
testable without touching the host.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

try:  # pragma: no cover - POSIX only
    import grp
except ImportError:  # pragma: no cover
    grp = None


DEFAULT_GROUP = "srvmgrs"
DEFAULT_SOCKET = "/run/smanager/smanagerd.sock"
DEFAULT_CONFIG = "/etc/smanager/smanager.yaml"
DEFAULT_UNIT_DIR = "/etc/systemd/system"
SERVICE_NAME = "smanagerd.service"
SOCKET_NAME = "smanagerd.socket"

RunCommand = Callable[..., subprocess.CompletedProcess]


def render_socket_unit(socket_path: str, group: str) -> str:
    return (
        "[Unit]\n"
        "Description=SManager daemon socket\n"
        "\n"
        "[Socket]\n"
        f"ListenStream={socket_path}\n"
        "SocketMode=0660\n"
        "SocketUser=root\n"
        f"SocketGroup={group}\n"
        "Accept=no\n"
        "\n"
        "[Install]\n"
        "WantedBy=sockets.target\n"
    )


def render_service_unit(
    exec_path: str,
    config_path: str,
    socket_path: str,
    group: str,
    user: str = "root",
) -> str:
    return (
        "[Unit]\n"
        "Description=SManager privileged daemon\n"
        "Requires=smanagerd.socket\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        f"Type=simple\n"
        f"User={user}\n"
        f"ExecStart={exec_path} --config {config_path} --socket {socket_path} --group {group}\n"
        "Restart=on-failure\n"
        "RestartSec=2\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _default_runner(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(*args, capture_output=True, text=True, check=True, **kwargs)


@dataclass
class InstallReport:
    action: str
    dry_run: bool
    root: str
    group: str = DEFAULT_GROUP
    socket: str = DEFAULT_SOCKET
    config: str = DEFAULT_CONFIG
    files: dict[str, str] = field(default_factory=dict)
    commands: list[list[str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "dry_run": self.dry_run,
            "group": self.group,
            "socket": self.socket,
            "config": self.config,
            "files": sorted(self.files),
            "commands": self.commands,
            "notes": self.notes,
        }


class Installer:
    def __init__(
        self,
        *,
        root: str = "/",
        group: str = DEFAULT_GROUP,
        socket: str = DEFAULT_SOCKET,
        config: str = DEFAULT_CONFIG,
        exec_path: Optional[str] = None,
        user: str = "root",
        unit_dir: str = DEFAULT_UNIT_DIR,
        dry_run: bool = False,
        run: Optional[RunCommand] = None,
        group_exists: Optional[Callable[[str], bool]] = None,
    ):
        self.root = root
        self.group = group
        self.socket = socket
        self.config = config
        self.user = user
        self.exec_path = exec_path or self._detect_exec_path()
        self.unit_dir = os.path.join(root, unit_dir.lstrip("/"))
        self.dry_run = dry_run
        self._run = run or _default_runner
        self._group_exists = group_exists or self._system_group_exists

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _detect_exec_path() -> Optional[str]:
        """Best-effort location of the ``smanagerd`` executable.

        ``sudo`` uses a restricted PATH (``secure_path``), so with pipx the
        daemon binary is often not on root's PATH. We therefore fall back to the
        sibling of the running ``smanager`` CLI (both live in the same bin dir,
        e.g. ``~/.local/bin``).
        """
        found = shutil.which("smanagerd")
        if found:
            return found
        argv0 = None
        try:
            argv0 = sys.argv[0]
        except (IndexError, AttributeError):
            argv0 = None
        candidates = []
        if argv0:
            candidates.append(os.path.join(os.path.dirname(os.path.realpath(argv0)), "smanagerd"))
        candidates.append(os.path.join(os.path.dirname(os.path.realpath(sys.executable)), "smanagerd"))
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate
        return None

    @staticmethod
    def _system_group_exists(name: str) -> bool:
        if grp is None:
            return False
        try:
            grp.getgrnam(name)
            return True
        except KeyError:
            return False

    def _write(self, path: str, content: str, mode: int = 0o644) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(path, mode)

    def _unit_path(self, name: str) -> str:
        return os.path.join(self.unit_dir, name)

    def _run_cmd(self, args: list[str], report: InstallReport) -> None:
        report.commands.append(args)
        if not self.dry_run:
            self._run(args)

    # -- actions -----------------------------------------------------------
    def install(self) -> InstallReport:
        report = InstallReport(action="install", dry_run=self.dry_run, root=self.root,
                               group=self.group, socket=self.socket, config=self.config)

        exec_path = self.exec_path
        if not exec_path:
            if not self.dry_run:
                raise ValueError(
                    "could not locate the 'smanagerd' executable. Run as the user who "
                    "installed smanager (e.g. 'sudo \"$(command -v smanager)\" daemon install') "
                    "or pass --exec-path /path/to/smanagerd."
                )
            exec_path = "smanagerd"
            report.notes.append(
                "'smanagerd' not found on PATH; the generated unit is a preview. "
                "Pass --exec-path to render the real path."
            )

        if self._group_exists(self.group):
            report.notes.append(f"group '{self.group}' already exists")
        else:
            self._run_cmd(["groupadd", "--system", self.group], report)

        files = {
            self._unit_path(SOCKET_NAME): render_socket_unit(self.socket, self.group),
            self._unit_path(SERVICE_NAME): render_service_unit(
                exec_path, self.config, self.socket, self.group, self.user
            ),
        }
        for path, content in files.items():
            report.files[path] = content
            if not self.dry_run:
                self._write(path, content)

        self._run_cmd(["systemctl", "daemon-reload"], report)
        self._run_cmd(["systemctl", "enable", "--now", SOCKET_NAME], report)
        return report

    def uninstall(self) -> InstallReport:
        report = InstallReport(action="uninstall", dry_run=self.dry_run, root=self.root,
                               group=self.group, socket=self.socket, config=self.config)

        self._run_cmd(["systemctl", "disable", "--now", SOCKET_NAME], report)
        for name in (SERVICE_NAME, SOCKET_NAME):
            path = self._unit_path(name)
            report.files[path] = ""
            if not self.dry_run and os.path.exists(path):
                os.unlink(path)
        self._run_cmd(["systemctl", "daemon-reload"], report)
        return report

    def status(self) -> dict:
        try:
            result = self._run(["systemctl", "is-active", SOCKET_NAME], check=False)
            active = (result.stdout or "").strip()
        except (OSError, subprocess.SubprocessError) as exc:
            return {"active": "unknown", "error": str(exc)}
        return {"active": active or "unknown", "service": SOCKET_NAME}
