import subprocess

import pytest

import smanager.service_managers.local_manager as lm
from smanager.datatypes import Service, ServiceMetadata
from smanager.events import ManagerEventDispatcher
from smanager.service_managers.local_manager import LocalManager


def make_manager(tmp_path, *, privilege=None, global_privilege="auto", **local_extra):
    service_dir = tmp_path / "svc"
    service_dir.mkdir()
    local = {"systemd_services": ["main_menu.service"], **local_extra}
    if privilege is not None:
        local["privilege"] = privilege
    metadata = ServiceMetadata.from_dict(
        {
            "name": "App",
            "description": "x",
            "schema_version": 2,
            "id": "app",
            "active": True,
            "runtime": {
                "type": "local",
                "ports": {"webui": 1234},
                "sys_user": "u",
                "sys_group": "g",
            },
            "local": local,
        }
    )
    service = Service(
        metadata=metadata,
        service_abspath=str(service_dir),
        metadata_filename="sd_info.json",
    )
    manager = LocalManager(service, vpn=None)
    manager.systemd_privilege = global_privilege
    return manager


class Recorder:
    def __init__(self, failures=()):
        self.calls = []
        self.failures = set(failures)

    def __call__(self, command, capture_output=True, text=True, check=True):
        self.calls.append(list(command))
        kind = "sudo" if command[0] == "sudo" else "direct"
        if kind in self.failures:
            raise subprocess.CalledProcessError(
                1, command, stderr="Access denied: requires interactive authentication"
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def test_auto_direct_success(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    recorder = Recorder()
    monkeypatch.setattr(lm.subprocess, "run", recorder)
    manager._run_systemd("start", "main_menu.service")
    assert recorder.calls == [["systemctl", "start", "main_menu.service"]]


def test_auto_falls_back_to_sudo_n(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    recorder = Recorder(failures={"direct"})
    monkeypatch.setattr(lm.subprocess, "run", recorder)
    manager._run_systemd("start", "main_menu.service")
    assert recorder.calls == [
        ["systemctl", "start", "main_menu.service"],
        ["sudo", "-n", "systemctl", "start", "main_menu.service"],
    ]


def test_auto_all_fail_actionable_error(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    recorder = Recorder(failures={"direct", "sudo"})
    monkeypatch.setattr(lm.subprocess, "run", recorder)
    with pytest.raises(RuntimeError) as excinfo:
        manager._run_systemd("start", "main_menu.service")
    message = str(excinfo.value)
    assert "NOPASSWD" in message
    assert "local.privilege" in message


def test_sudo_privilege_skips_direct(tmp_path, monkeypatch):
    manager = make_manager(tmp_path, privilege="sudo")
    recorder = Recorder()
    monkeypatch.setattr(lm.subprocess, "run", recorder)
    manager._run_systemd("stop", "main_menu.service")
    assert recorder.calls == [["sudo", "-n", "systemctl", "stop", "main_menu.service"]]


def test_none_privilege_never_uses_sudo(tmp_path, monkeypatch):
    manager = make_manager(tmp_path, privilege="none")
    recorder = Recorder(failures={"direct"})
    monkeypatch.setattr(lm.subprocess, "run", recorder)
    with pytest.raises(RuntimeError):
        manager._run_systemd("start", "main_menu.service")
    assert all(call[0] != "sudo" for call in recorder.calls)


def test_global_default_used_when_no_service_privilege(tmp_path, monkeypatch):
    manager = make_manager(tmp_path, global_privilege="sudo")
    recorder = Recorder()
    monkeypatch.setattr(lm.subprocess, "run", recorder)
    manager._run_systemd("start", "main_menu.service")
    assert recorder.calls == [["sudo", "-n", "systemctl", "start", "main_menu.service"]]


def test_restart_reports_stop_warning(tmp_path, monkeypatch):
    dispatcher = ManagerEventDispatcher()
    events = []
    dispatcher.on(events.append)

    manager = make_manager(tmp_path)
    manager.event_dispatcher = dispatcher

    def failing_stop():
        raise RuntimeError("stop needs privileges")

    monkeypatch.setattr(manager, "stop", failing_stop)
    monkeypatch.setattr(manager, "start", lambda: None)

    manager.restart()

    after = [e for e in events if e.action == "restart" and e.phase == "after"]
    assert after
    assert after[-1].payload.get("stop_warning") == "stop needs privileges"
