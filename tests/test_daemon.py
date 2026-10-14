import json
import os
import socket
import tempfile
import threading
import time

import pytest

from smanager.daemon import protocol
from smanager.daemon.authz import Authorizer, PeerCredentials
from smanager.daemon.client import DaemonClient, DaemonConnectionError, DaemonError
from smanager.daemon.server import DaemonServer
from smanager.datatypes import Service, ServiceMetadata, ServiceStatus, SingleStatus
from smanager.events import ManagerEvent, ManagerEventDispatcher


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------
def test_protocol_roundtrip():
    msg = protocol.make_request(1, "daemon.ping", {})
    assert protocol.decode_message(protocol.encode_message(msg)[:-1]) == msg
    assert protocol.make_response(1, {"x": 1})["ok"] is True
    err = protocol.make_error(2, protocol.ProtocolError(protocol.ERR_NOT_FOUND, "nope").to_error())
    assert err["error"]["code"] == "not_found"
    assert protocol.make_event(3, {"phase": "before"})["event"]["phase"] == "before"


def test_protocol_invalid_json():
    with pytest.raises(protocol.ProtocolError) as exc:
        protocol.decode_message(b"{not json")
    assert exc.value.code == protocol.ERR_BAD_REQUEST


def test_protocol_frame_too_large():
    with pytest.raises(protocol.ProtocolError):
        protocol.encode_message({"blob": "x" * (protocol.MAX_FRAME_BYTES + 10)})


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
def test_authorizer_open_and_restricted():
    assert Authorizer().authorize(PeerCredentials(pid=1, uid=1000, gid=1000)) is True

    only_root = Authorizer(allowed_uids=[0])
    assert only_root.authorize(PeerCredentials(pid=1, uid=0, gid=0)) is True
    assert only_root.authorize(PeerCredentials(pid=1, uid=1000, gid=1000)) is False

    by_group = Authorizer(allowed_gids=[4242])
    assert by_group.authorize(PeerCredentials(pid=1, uid=1000, gid=4242)) is True


# ---------------------------------------------------------------------------
# Fake backend
# ---------------------------------------------------------------------------
class FakeManager:
    def __init__(self, services):
        self.services = services
        self.event_dispatcher = ManagerEventDispatcher()

    def on(self, callback, event_name=None):
        self.event_dispatcher.on(callback, event_name)

    def get_service(self, service_id):
        for service in self.services:
            if service.metadata.id == service_id:
                return service
        raise ValueError(f"Service with ID '{service_id}' not found.")

    def get_status(self, service_id, check_updates=False):
        service = self.get_service(service_id)
        return ServiceStatus(
            id=service_id,
            type=service.metadata.runtime.type,
            statuses=[SingleStatus(name="main_menu.service", status="running")],
            enabled=True,
        )

    def manage_service(self, service_id, action, dry_run=False):
        service = self.get_service(service_id)
        self.event_dispatcher.emit(ManagerEvent(
            name=f"service.{action}.before", scope="service", action=action,
            phase="before", source="FakeManager", service_id=service_id,
        ))
        if service_id == "broken":
            raise RuntimeError("boom")
        self.event_dispatcher.emit(ManagerEvent(
            name=f"service.{action}.after", scope="service", action=action,
            phase="after", source="FakeManager", service_id=service_id,
        ))

    def manage_group(self, group_name, action, dry_run=False):
        self.event_dispatcher.emit(ManagerEvent(
            name=f"group.{action}.before", scope="group", action=action,
            phase="before", source="FakeManager", group_name=group_name,
        ))
        self.event_dispatcher.emit(ManagerEvent(
            name=f"group.{action}.after", scope="group", action=action,
            phase="after", source="FakeManager", group_name=group_name,
        ))

    def manage_by_dependency(self, dependency_name, action, dry_run=False):
        self.event_dispatcher.emit(ManagerEvent(
            name=f"dependency.{action}.after", scope="dependency", action=action,
            phase="after", source="FakeManager", dependency_name=dependency_name,
        ))

    def manage_all(self, action, dry_run=False):
        self.event_dispatcher.emit(ManagerEvent(
            name=f"all.{action}.after", scope="all", action=action,
            phase="after", source="FakeManager",
        ))

    def discover_services(self):
        return self.services


def _make_service(tmp_path, service_id="demo", active=True):
    service_dir = tmp_path / service_id
    service_dir.mkdir()
    metadata = ServiceMetadata.from_dict({
        "name": service_id.title(),
        "description": "demo",
        "schema_version": 2,
        "id": service_id,
        "active": active,
        "runtime": {"type": "local", "ports": {"webui": 1}, "sys_user": "u", "sys_group": "g"},
        "local": {"systemd_services": ["main_menu.service"]},
    })
    return Service(metadata=metadata, service_abspath=str(service_dir), metadata_filename="sd_info.json")


@pytest.fixture
def daemon_env(tmp_path):
    services = [_make_service(tmp_path, "demo"), _make_service(tmp_path, "broken")]
    manager = FakeManager(services)

    runtime_dir = tempfile.mkdtemp(prefix="smd-")
    socket_path = os.path.join(runtime_dir, "s.sock")
    server = DaemonServer(manager, socket_path)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for _ in range(200):
        if os.path.exists(socket_path):
            break
        time.sleep(0.01)
    time.sleep(0.05)

    yield {"manager": manager, "server": server, "socket_path": socket_path}

    server.shutdown()
    thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Server + client
# ---------------------------------------------------------------------------
def test_client_basic_calls(daemon_env):
    with DaemonClient(daemon_env["socket_path"]) as client:
        assert client.ping() is True
        version = client.version()
        assert version["name"] == "smanagerd"
        assert version["protocol"] == protocol.PROTOCOL_VERSION

        services = client.list_services()
        assert {s["id"] for s in services} == {"demo", "broken"}

        info = client.info("demo")
        assert info["id"] == "demo"
        assert info["metadata"]["runtime"]["type"] == "local"

        status = client.status("demo")
        assert status["id"] == "demo"
        assert status["statuses"][0]["status"] == "running"


def test_action_streams_events(daemon_env):
    events = []
    with DaemonClient(daemon_env["socket_path"]) as client:
        result = client.action("demo", "start", on_event=events.append)
    assert result["ok"] is True
    phases = [e["phase"] for e in events]
    assert "before" in phases and "after" in phases
    assert all(e["service_id"] == "demo" for e in events)


def test_action_unsupported(daemon_env):
    with DaemonClient(daemon_env["socket_path"]) as client:
        with pytest.raises(DaemonError) as exc:
            client.action("demo", "explode")
    assert exc.value.code == protocol.ERR_UNSUPPORTED_ACTION


def test_unknown_service(daemon_env):
    with DaemonClient(daemon_env["socket_path"]) as client:
        with pytest.raises(DaemonError) as exc:
            client.info("does-not-exist")
    assert exc.value.code == protocol.ERR_NOT_FOUND


def test_internal_error_is_structured(daemon_env):
    with DaemonClient(daemon_env["socket_path"]) as client:
        with pytest.raises(DaemonError) as exc:
            client.action("broken", "start")
    assert exc.value.code == protocol.ERR_INTERNAL
    assert "boom" in exc.value.message


def test_unknown_method(daemon_env):
    with DaemonClient(daemon_env["socket_path"]) as client:
        with pytest.raises(DaemonError) as exc:
            client.request("no.such.method")
    assert exc.value.code == protocol.ERR_UNKNOWN_METHOD


def test_reconnect_after_close(daemon_env):
    client = DaemonClient(daemon_env["socket_path"])
    client.connect()
    assert client.ping() is True
    client.close()
    assert client.ping() is True  # reconnects lazily
    client.close()


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------
def test_connect_when_daemon_down():
    client = DaemonClient("/tmp/smanager-does-not-exist.sock", timeout=1)
    with pytest.raises(DaemonConnectionError):
        client.connect()


def test_request_timeout_via_silent_server():
    runtime_dir = tempfile.mkdtemp(prefix="smd-silent-")
    socket_path = os.path.join(runtime_dir, "s.sock")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(1)
    stop = threading.Event()

    def accept_and_silence():
        conn, _ = listener.accept()
        stop.wait(5)
        conn.close()

    threading.Thread(target=accept_and_silence, daemon=True).start()
    try:
        client = DaemonClient(socket_path, timeout=0.3)
        with pytest.raises(DaemonError) as exc:
            client.connect()
        assert exc.value.code == protocol.ERR_TIMEOUT
    finally:
        stop.set()
        listener.close()


def test_unauthorized_peer(tmp_path):
    services = [_make_service(tmp_path, "demo")]
    manager = FakeManager(services)
    runtime_dir = tempfile.mkdtemp(prefix="smd-auth-")
    socket_path = os.path.join(runtime_dir, "s.sock")
    server = DaemonServer(manager, socket_path, allowed_uids=[os.getuid() + 1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for _ in range(200):
        if os.path.exists(socket_path):
            break
        time.sleep(0.01)
    time.sleep(0.05)
    try:
        client = DaemonClient(socket_path, timeout=2)
        with pytest.raises(DaemonError) as exc:
            client.connect()
        assert exc.value.code == protocol.ERR_UNAUTHORIZED
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_group_action_streams_group_events(daemon_env):
    events = []
    with DaemonClient(daemon_env["socket_path"]) as client:
        result = client.group_action("media", "restart", on_event=events.append)
    assert result["ok"] is True
    assert {"group"} == {e["scope"] for e in events}
    assert any(e["phase"] == "after" for e in events)


# ---------------------------------------------------------------------------
# CLI routing through the daemon
# ---------------------------------------------------------------------------
def test_cli_routes_action_through_daemon(daemon_env):
    from click.testing import CliRunner
    from smanager.cli.main import cli

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--daemon-socket", daemon_env["socket_path"], "service", "start", "demo"]
    )
    assert result.exit_code == 0, result.output
    assert "[OK] 'start' on service 'demo'." in result.output


def test_cli_routes_group_action_through_daemon(daemon_env):
    from click.testing import CliRunner
    from smanager.cli.main import cli

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--daemon-socket", daemon_env["socket_path"], "group", "restart", "media"]
    )
    assert result.exit_code == 0, result.output
    assert "[OK] 'restart' on group 'media'." in result.output


def test_cli_daemon_forced_but_down():
    from click.testing import CliRunner
    from smanager.cli.main import cli

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--daemon", "--daemon-socket", "/tmp/smanager-nope.sock", "service", "start", "demo"]
    )
    assert result.exit_code != 0
    assert "cannot connect" in result.output.lower()


def test_concurrent_clients(daemon_env):
    results = []

    def worker():
        with DaemonClient(daemon_env["socket_path"]) as client:
            results.append(client.action("demo", "restart")["ok"])

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert results == [True] * 5
