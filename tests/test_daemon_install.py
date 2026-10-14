import json
import os
import subprocess

from click.testing import CliRunner

from smanager.cli.main import cli
from smanager.daemon.install import (
    SERVICE_NAME,
    SOCKET_NAME,
    Installer,
    render_service_unit,
    render_socket_unit,
)


class FakeSystem:
    def __init__(self):
        self.groups = set()
        self.commands = []

    def run(self, args, **kwargs):
        self.commands.append(list(args))
        if args[0] == "groupadd":
            self.groups.add(args[-1])
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def group_exists(self, name):
        return name in self.groups


def test_render_units():
    socket_unit = render_socket_unit("/run/smanager/smanagerd.sock", "srvmgrs")
    assert "ListenStream=/run/smanager/smanagerd.sock" in socket_unit
    assert "SocketMode=0660" in socket_unit
    assert "SocketGroup=srvmgrs" in socket_unit

    service_unit = render_service_unit("/usr/bin/smanagerd", "/etc/smanager/smanager.yaml",
                                       "/run/smanager/smanagerd.sock", "srvmgrs")
    assert "ExecStart=/usr/bin/smanagerd --config /etc/smanager/smanager.yaml" in service_unit
    assert "Requires=smanagerd.socket" in service_unit


def test_install_idempotent(tmp_path):
    system = FakeSystem()
    installer = Installer(
        root=str(tmp_path),
        run=system.run,
        group_exists=system.group_exists,
        exec_path="/usr/bin/smanagerd",
    )

    report = installer.install()
    unit_dir = tmp_path / "etc/systemd/system"
    assert (unit_dir / SOCKET_NAME).is_file()
    assert (unit_dir / SERVICE_NAME).is_file()
    assert ["groupadd", "--system", "srvmgrs"] in report.commands
    assert ["systemctl", "enable", "--now", SOCKET_NAME] in report.commands

    # Second run must not re-create the group.
    report2 = installer.install()
    assert not any(cmd[0] == "groupadd" for cmd in report2.commands)
    assert any("already exists" in note for note in report2.notes)


def test_install_dry_run_writes_nothing(tmp_path):
    system = FakeSystem()
    report = Installer(root=str(tmp_path), run=system.run, group_exists=system.group_exists,
                       dry_run=True).install()
    assert report.dry_run is True
    assert report.files
    assert not (tmp_path / "etc").exists()
    assert system.commands == []  # runner never invoked


def test_uninstall_removes_units(tmp_path):
    system = FakeSystem()
    installer = Installer(root=str(tmp_path), run=system.run, group_exists=system.group_exists)
    installer.install()
    unit_dir = tmp_path / "etc/systemd/system"
    assert (unit_dir / SOCKET_NAME).is_file()

    report = installer.uninstall()
    assert not (unit_dir / SOCKET_NAME).exists()
    assert ["systemctl", "disable", "--now", SOCKET_NAME] in report.commands


def test_cli_install_dry_run_json():
    runner = CliRunner()
    result = runner.invoke(cli, ["daemon", "install", "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["action"] == "install"
    assert payload["dry_run"] is True
