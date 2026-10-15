import os
import subprocess
from pathlib import Path

import pytest

import smanager.service_managers.base_sdv2_manager as bsm
from smanager.datatypes import Service, ServiceMetadata, UpdateSection
from smanager.service_managers.docker_manager import DockerManager
from smanager.service_managers.local_manager import LocalManager

try:
    import grp
    import pwd
except ImportError:  # pragma: no cover
    grp = None
    pwd = None

pytestmark = pytest.mark.skipif(pwd is None or grp is None, reason="POSIX only")


def _current_user() -> str:
    return pwd.getpwuid(os.getuid()).pw_name


def _current_group() -> str:
    return grp.getgrgid(os.getgid()).gr_name


def _make_manager(tmp_path, sys_user, sys_group):
    service_dir = tmp_path / "svc"
    service_dir.mkdir()
    (service_dir / "start.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    metadata = ServiceMetadata.from_dict({
        "name": "App",
        "description": "x",
        "schema_version": 2,
        "id": "app",
        "active": True,
        "runtime": {"type": "local", "ports": {"webui": 1}, "sys_user": sys_user, "sys_group": sys_group},
        "local": {"systemd_services": ["app.service"]},
        "scripts": {"start": "start.sh"},
    })
    service = Service(metadata=metadata, service_abspath=str(service_dir), metadata_filename="sd_info.json")
    return LocalManager(service, vpn=None)


class Recorder:
    def __init__(self):
        self.kwargs = None

    def __call__(self, argv, **kwargs):
        self.kwargs = kwargs
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


@pytest.fixture(autouse=True)
def _reset_drop():
    bsm.set_script_privilege_drop(False)
    yield
    bsm.set_script_privilege_drop(False)


def test_drop_disabled_keeps_current_user(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path, _current_user(), _current_group())
    recorder = Recorder()
    monkeypatch.setattr(bsm.subprocess, "run", recorder)
    manager._run_script("start")
    assert "user" not in recorder.kwargs
    assert "group" not in recorder.kwargs


def test_drop_enabled_uses_service_user(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path, _current_user(), _current_group())
    recorder = Recorder()
    monkeypatch.setattr(bsm.subprocess, "run", recorder)
    bsm.set_script_privilege_drop(True)
    manager._run_script("start")
    assert recorder.kwargs["user"] == os.getuid()
    assert recorder.kwargs["group"] == os.getgid()


def test_drop_unresolvable_user_is_ignored(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path, "no-such-user-xyz", "no-such-group-xyz")
    recorder = Recorder()
    monkeypatch.setattr(bsm.subprocess, "run", recorder)
    bsm.set_script_privilege_drop(True)
    manager._run_script("start")
    assert "user" not in recorder.kwargs


def test_inline_update_command_drops_when_enabled(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path, _current_user(), _current_group())
    recorder = Recorder()
    monkeypatch.setattr(bsm.subprocess, "run", recorder)
    bsm.set_script_privilege_drop(True)
    manager._process_run(["echo", "hi"], cwd=str(tmp_path), drop=True)
    assert recorder.kwargs["user"] == os.getuid()


def test_process_run_no_drop_by_default(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path, _current_user(), _current_group())
    recorder = Recorder()
    monkeypatch.setattr(bsm.subprocess, "run", recorder)
    bsm.set_script_privilege_drop(True)
    manager._process_run(["docker", "compose", "pull"], cwd=str(tmp_path))
    assert "user" not in recorder.kwargs


def test_update_git_strategy_drops(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path, _current_user(), _current_group())
    manager.service.metadata.update = UpdateSection(strategy="auto")
    (Path(manager.service.service_abspath) / ".git").mkdir()

    captured = {}

    def fake_process(command, cwd=None, drop=False):
        captured["drop"] = drop
        return None

    monkeypatch.setattr(manager, "_process_run", fake_process)
    monkeypatch.setattr(manager, "restart", lambda: None)
    bsm.set_script_privilege_drop(True)

    manager.update()
    assert captured["drop"] is True


def test_update_command_strategy_drops(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path, _current_user(), _current_group())
    manager.service.metadata.update = UpdateSection(strategy="command", command="touch marker")

    captured = {}

    def fake_process(command, cwd=None, drop=False):
        captured["drop"] = drop
        return None

    monkeypatch.setattr(manager, "_process_run", fake_process)
    bsm.set_script_privilege_drop(True)

    manager.update()
    assert captured["drop"] is True


def test_update_docker_strategy_does_not_drop(tmp_path, monkeypatch):
    service_dir = tmp_path / "dockersvc"
    service_dir.mkdir()
    (service_dir / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    metadata = ServiceMetadata.from_dict({
        "name": "App",
        "description": "x",
        "schema_version": 2,
        "id": "app",
        "active": True,
        "runtime": {"type": "docker", "ports": {"webui": 1}, "sys_user": "u", "sys_group": "g"},
        "docker": {"compose_file": "compose.yaml"},
        "update": {"strategy": "docker"},
    })
    service = Service(metadata=metadata, service_abspath=str(service_dir), metadata_filename="sd_info.json")
    manager = DockerManager(service, vpn=None)

    captured = {}

    def fake_process(command, cwd=None, drop=False):
        captured["drop"] = drop
        return None

    monkeypatch.setattr(manager, "_process_run", fake_process)
    bsm.set_script_privilege_drop(True)

    manager.update()
    assert captured["drop"] is False
