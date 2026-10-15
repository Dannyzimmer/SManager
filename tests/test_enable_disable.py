import json
import os

from smanager.datatypes import Service, ServiceMetadata
from smanager.metadata_ops import atomic_write_json
from smanager.service_managers.local_manager import LocalManager


def _make_manager(tmp_path, active=True):
    service_dir = tmp_path / "svc"
    service_dir.mkdir()
    data = {
        "name": "App",
        "description": "x",
        "schema_version": 2,
        "id": "app",
        "active": active,
        "runtime": {"type": "local", "ports": {"webui": 1}, "sys_user": "u", "sys_group": "g"},
        "local": {"systemd_services": ["app.service"]},
        "custom_key": {"keep": 1},
    }
    metadata_path = service_dir / "sd_info.json"
    metadata_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
    metadata = ServiceMetadata.from_dict(data)
    service = Service(metadata=metadata, service_abspath=str(service_dir), metadata_filename="sd_info.json")
    return LocalManager(service, vpn=None), metadata_path


def test_atomic_write_preserves_mode_and_owner(tmp_path):
    path = tmp_path / "x.json"
    path.write_text("{}", encoding="utf-8")
    os.chmod(path, 0o640)
    before = path.stat()

    atomic_write_json(path, {"a": 1})

    after = path.stat()
    assert (after.st_mode & 0o7777) == 0o640
    assert after.st_uid == before.st_uid
    assert after.st_gid == before.st_gid
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}


def test_enable_preserves_mode_owner_and_unknown_keys(tmp_path):
    manager, metadata_path = _make_manager(tmp_path, active=False)
    os.chmod(metadata_path, 0o640)
    before = metadata_path.stat()

    manager.enable()

    after = metadata_path.stat()
    assert (after.st_mode & 0o7777) == 0o640
    assert after.st_uid == before.st_uid
    saved = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert saved["active"] is True
    assert saved["custom_key"] == {"keep": 1}  # unknown keys preserved


def test_disable_sets_inactive(tmp_path):
    manager, metadata_path = _make_manager(tmp_path, active=True)
    manager.disable()
    saved = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert saved["active"] is False


def test_enable_emits_events(tmp_path):
    from smanager.events import ManagerEventDispatcher

    manager, _ = _make_manager(tmp_path, active=False)
    dispatcher = ManagerEventDispatcher()
    events = []
    dispatcher.on(events.append)
    manager.event_dispatcher = dispatcher

    manager.enable()

    phases = [(e.action, e.phase) for e in events]
    assert ("enable", "before") in phases
    assert ("enable", "after") in phases
