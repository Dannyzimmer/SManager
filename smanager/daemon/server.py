"""The SManager daemon server.

A narrow, validated API over a local Unix socket. It reuses the existing
``GlobalManager`` for discovery and lifecycle operations and streams
``ManagerEvent`` progress to the caller while an action runs.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import socketserver
import threading
from collections import defaultdict
from typing import Any, Optional

from .. import __version__
from ..datatypes import GlobalConfig
from ..global_manager import GlobalManager
from ..service_managers import base_sdv2_manager
from ..vpn import get_vpn
from . import protocol
from .authz import Authorizer, PeerCredentials, get_peer_credentials
from .catalog import Catalog

logger = logging.getLogger("smanagerd")
audit_logger = logging.getLogger("smanagerd.audit")

# Actions exposed in Phase 1. Extended in later phases.
SERVICE_ACTIONS = {"start", "stop", "restart"}

DEFAULT_SOCKET_PATH = "/run/smanager/smanagerd.sock"
LISTEN_FDS_START = 3


def _systemd_socket():
    """Return the socket passed by systemd socket activation, or None.

    systemd sets ``LISTEN_PID``/``LISTEN_FDS`` and passes the listening file
    descriptor starting at fd 3. When present we must adopt it instead of
    binding our own socket (otherwise the connection that triggered activation
    is left unaccepted on systemd's socket and the client hangs).
    """
    if os.environ.get("LISTEN_PID") != str(os.getpid()):
        return None
    try:
        count = int(os.environ.get("LISTEN_FDS", "0"))
    except ValueError:
        return None
    if count < 1:
        return None
    import socket as _socket

    return _socket.socket(fileno=LISTEN_FDS_START)


class DaemonServer:
    def __init__(
        self,
        manager,
        socket_path: str = DEFAULT_SOCKET_PATH,
        *,
        allowed_uids: Optional[list[int]] = None,
        allowed_gids: Optional[list[int]] = None,
        socket_group: Optional[str] = None,
    ):
        self.manager = manager
        self.socket_path = socket_path
        self.socket_group = socket_group
        self.authorizer = Authorizer(allowed_uids=allowed_uids, allowed_gids=allowed_gids)
        self.catalog = Catalog(manager)
        self._tls = threading.local()
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._server: Optional[_UnixStreamServer] = None
        self._owns_socket = True

        # One global forwarder: it routes events to the handler that is
        # currently executing the request on this thread.
        if hasattr(manager, "on"):
            manager.on(self._on_event)

    # -- event forwarding --------------------------------------------------
    def _on_event(self, event) -> None:
        handler = getattr(self._tls, "handler", None)
        if handler is None:
            return
        request_id = getattr(self._tls, "request_id", None)
        handler.send_event(request_id, event.to_dict())

    # -- audit -------------------------------------------------------------
    @staticmethod
    def audit(event: str, *, creds: Optional[PeerCredentials] = None, **fields: Any) -> None:
        record = {"event": event}
        if creds is not None:
            record.update({"uid": creds.uid, "gid": creds.gid, "pid": creds.pid})
        record.update(fields)
        audit_logger.info(json.dumps(record, separators=(",", ":")))

    # -- authorization -----------------------------------------------------
    def authorize(self, creds: Optional[PeerCredentials]) -> bool:
        return self.authorizer.authorize(creds)

    # -- dispatch ----------------------------------------------------------
    def dispatch(self, request: dict, handler: "_RequestHandler", creds) -> Any:
        method = request.get("method")
        params = request.get("params") or {}
        if not isinstance(method, str):
            raise protocol.ProtocolError(protocol.ERR_BAD_REQUEST, "missing 'method'")
        if not isinstance(params, dict):
            raise protocol.ProtocolError(protocol.ERR_BAD_REQUEST, "params must be an object")

        if method == "hello":
            return self._handle_hello(params)
        if method == "daemon.ping":
            return {"pong": True}
        if method == "daemon.version":
            return {"name": "smanagerd", "version": __version__, "protocol": protocol.PROTOCOL_VERSION}
        if method == "catalog.list":
            return {"services": self.catalog.list_summary()}
        if method == "catalog.reload":
            count = self.catalog.reload()
            return {"reloaded": True, "count": count}
        if method == "service.info":
            return self._handle_service_info(params)
        if method == "service.status":
            return self._handle_service_status(params)
        if method == "service.action":
            return self._handle_service_action(params, handler, request.get("id"), creds)
        if method == "group.action":
            return self._handle_collection_action("group", params, handler, request.get("id"), creds)
        if method == "dependency.action":
            return self._handle_collection_action("dependency", params, handler, request.get("id"), creds)
        if method == "all.action":
            return self._handle_collection_action("all", params, handler, request.get("id"), creds)

        raise protocol.ProtocolError(protocol.ERR_UNKNOWN_METHOD, f"unknown method '{method}'")

    def _handle_hello(self, params: dict) -> dict:
        client_protocol = params.get("protocol", protocol.PROTOCOL_VERSION)
        if client_protocol != protocol.PROTOCOL_VERSION:
            raise protocol.ProtocolError(
                protocol.ERR_PROTOCOL_MISMATCH,
                f"unsupported protocol {client_protocol}; server speaks {protocol.PROTOCOL_VERSION}",
            )
        return {
            "protocol": protocol.PROTOCOL_VERSION,
            "server": "smanagerd",
            "version": __version__,
        }

    def _require_id(self, params: dict) -> str:
        service_id = params.get("id")
        if not isinstance(service_id, str) or not service_id:
            raise protocol.ProtocolError(protocol.ERR_BAD_REQUEST, "missing 'id'")
        return service_id

    def _handle_service_info(self, params: dict) -> dict:
        service = self._get_service(self._require_id(params))
        return {
            "id": service.metadata.id,
            "path": os.path.join(service.service_abspath, service.metadata_filename),
            "service_dir": service.service_abspath,
            "metadata": dataclasses.asdict(service.metadata),
        }

    def _handle_service_status(self, params: dict) -> dict:
        service_id = self._require_id(params)
        check_updates = bool(params.get("check_updates", False))
        try:
            status = self.manager.get_status(service_id, check_updates=check_updates)
        except ValueError as exc:
            raise protocol.ProtocolError(protocol.ERR_NOT_FOUND, str(exc)) from exc
        return dataclasses.asdict(status)

    def _handle_service_action(self, params: dict, handler, request_id, creds) -> dict:
        service_id = self._require_id(params)
        action = params.get("action")
        if action not in SERVICE_ACTIONS:
            raise protocol.ProtocolError(
                protocol.ERR_UNSUPPORTED_ACTION,
                f"unsupported action '{action}'",
                {"supported": sorted(SERVICE_ACTIONS)},
            )
        dry_run = bool(params.get("dry_run", False))
        self._get_service(service_id)  # resolve/validate before acquiring the lock

        self._tls.handler = handler
        self._tls.request_id = request_id
        try:
            with self._locks[service_id]:
                self.manager.manage_service(service_id, action, dry_run=dry_run)
        finally:
            self._tls.handler = None
            self._tls.request_id = None

        self.audit("service.action", creds=creds, service_id=service_id, action=action, result="ok")
        return {"id": service_id, "action": action, "ok": True}

    def _handle_collection_action(self, scope: str, params: dict, handler, request_id, creds) -> dict:
        action = params.get("action")
        if action not in SERVICE_ACTIONS:
            raise protocol.ProtocolError(
                protocol.ERR_UNSUPPORTED_ACTION,
                f"unsupported action '{action}'",
                {"supported": sorted(SERVICE_ACTIONS)},
            )
        dry_run = bool(params.get("dry_run", False))
        identifier = None
        if scope == "group":
            identifier = params.get("group")
            if not isinstance(identifier, str) or not identifier:
                raise protocol.ProtocolError(protocol.ERR_BAD_REQUEST, "missing 'group'")
        elif scope == "dependency":
            identifier = params.get("dependency")
            if not isinstance(identifier, str) or not identifier:
                raise protocol.ProtocolError(protocol.ERR_BAD_REQUEST, "missing 'dependency'")

        self._tls.handler = handler
        self._tls.request_id = request_id
        try:
            if scope == "group":
                self.manager.manage_group(identifier, action, dry_run=dry_run)
            elif scope == "dependency":
                self.manager.manage_by_dependency(identifier, action, dry_run=dry_run)
            else:
                self.manager.manage_all(action, dry_run=dry_run)
        finally:
            self._tls.handler = None
            self._tls.request_id = None

        self.audit(
            f"{scope}.action", creds=creds,
            **{f"{scope}_name": identifier} if identifier else {},
            action=action, result="ok",
        )
        return {"scope": scope, "identifier": identifier, "action": action, "ok": True}

    def _get_service(self, service_id: str):
        try:
            return self.catalog.get(service_id)
        except ValueError as exc:
            raise protocol.ProtocolError(protocol.ERR_NOT_FOUND, str(exc)) from exc

    # -- lifecycle ---------------------------------------------------------
    def _build_server(self) -> "_UnixStreamServer":
        inherited = _systemd_socket()
        if inherited is not None:
            # systemd owns the socket (and its permissions); adopt the fd.
            server = _UnixStreamServer(self.socket_path, _RequestHandler, bind_and_activate=False)
            server.socket = inherited
            server.server_address = self.socket_path
            server.server_activate()
            server.daemon = self
            server.daemon_threads = True
            self._owns_socket = False
            logger.info("adopted systemd-activated socket at %s", self.socket_path)
            return server

        server = _UnixStreamServer(self.socket_path, _RequestHandler)
        server.daemon = self
        server.daemon_threads = True
        self._owns_socket = True
        self._apply_socket_permissions()
        return server

    def _apply_socket_permissions(self) -> None:
        try:
            os.chmod(self.socket_path, 0o660)
        except OSError:
            logger.warning("could not chmod socket %s", self.socket_path)
        if self.socket_group:
            import grp

            try:
                gid = grp.getgrnam(self.socket_group).gr_gid
                os.chown(self.socket_path, 0, gid)
            except (KeyError, OSError):
                logger.warning("could not set group %s on socket", self.socket_group)

    def serve_forever(self) -> None:
        parent = os.path.dirname(self.socket_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._server = self._build_server()
        logger.info(
            "smanagerd listening on %s (authorizer enforcing=%s)",
            self.socket_path,
            self.authorizer.enforcing,
        )
        try:
            self._server.serve_forever()
        finally:
            self._server.server_close()
            if getattr(self, "_owns_socket", True):
                try:
                    os.unlink(self.socket_path)
                except OSError:
                    pass

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.shutdown()


class _UnixStreamServer(socketserver.ThreadingUnixStreamServer):
    def server_bind(self) -> None:  # remove a stale socket before binding
        try:
            os.unlink(self.server_address)
        except OSError:
            pass
        super().server_bind()


class _RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        daemon: DaemonServer = self.server.daemon  # type: ignore[attr-defined]
        try:
            creds = get_peer_credentials(self.connection)
        except OSError:
            creds = None

        if not daemon.authorize(creds):
            self._send(protocol.make_error(None, protocol.ProtocolError(
                protocol.ERR_UNAUTHORIZED, "peer is not authorized to use the daemon"
            ).to_error()))
            return

        daemon.audit("connect", creds=creds)

        while True:
            line = self.rfile.readline(protocol.MAX_FRAME_BYTES + 1)
            if not line:
                break
            if len(line) > protocol.MAX_FRAME_BYTES or not line.endswith(b"\n"):
                self._send(protocol.make_error(
                    None,
                    protocol.ProtocolError(protocol.ERR_BAD_REQUEST, "frame too large or truncated").to_error(),
                ))
                break

            try:
                request = protocol.decode_message(line)
            except protocol.ProtocolError as exc:
                self._send(protocol.make_error(request_id=None, error=exc.to_error()))
                continue

            request_id = request.get("id")
            try:
                result = daemon.dispatch(request, self, creds)
            except protocol.ProtocolError as exc:
                self._send(protocol.make_error(request_id, exc.to_error()))
            except Exception as exc:  # noqa: BLE001 - never leak a traceback over the wire
                logger.exception("unhandled error while dispatching %s", request.get("method"))
                self._send(protocol.make_error(
                    request_id,
                    protocol.ProtocolError(protocol.ERR_INTERNAL, str(exc)).to_error(),
                ))
            else:
                self._send(protocol.make_response(request_id, result))

    def send_event(self, request_id: Optional[int], event: dict) -> None:
        self._send(protocol.make_event(request_id, event))

    def _send(self, message: dict) -> None:
        try:
            self.wfile.write(protocol.encode_message(message))
            self.wfile.flush()
        except OSError:
            pass


def build_manager(config_path: Optional[str]) -> GlobalManager:
    """Build a ``GlobalManager`` from a config file without the CLI layer."""
    path = config_path or os.environ.get("SMANAGER_CONFIG")
    if not path:
        raise SystemExit("smanagerd: no config file provided (use --config or SMANAGER_CONFIG)")
    try:
        with open(path) as handle:
            config = GlobalConfig.from_yaml(handle.read())
    except OSError as exc:
        raise SystemExit(f"smanagerd: cannot read config '{path}': {exc}")
    if not config.services_root or not os.path.isdir(config.services_root):
        raise SystemExit(f"smanagerd: services_root does not exist: {config.services_root!r}")
    try:
        vpn = get_vpn(config.vpn_provider)()
    except ValueError as exc:
        raise SystemExit(f"smanagerd: unknown VPN provider '{config.vpn_provider}': {exc}")
    return GlobalManager(config.services_root, config, vpn)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="smanagerd", description="SManager privileged daemon")
    parser.add_argument("--config", default=None, help="Path to smanager.yaml (or SMANAGER_CONFIG).")
    parser.add_argument(
        "--socket",
        default=os.environ.get("SMANAGER_SOCKET", DEFAULT_SOCKET_PATH),
        help="Unix socket path.",
    )
    parser.add_argument("--group", default=None, help="Group to own the socket (chown root:<group>).")
    parser.add_argument("--allow-uid", type=int, action="append", default=[], help="Allowed client uid.")
    parser.add_argument("--allow-gid", type=int, action="append", default=[], help="Allowed client gid.")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging.")
    parser.add_argument(
        "--no-drop-scripts",
        action="store_true",
        help="Run user-defined scripts/commands as the daemon user instead of dropping to the service user.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # By default the daemon drops privileges for user-defined scripts and inline
    # commands so they never run as root.
    base_sdv2_manager.set_script_privilege_drop(not args.no_drop_scripts)

    manager = build_manager(args.config)
    server = DaemonServer(
        manager,
        args.socket,
        allowed_uids=args.allow_uid,
        allowed_gids=args.allow_gid,
        socket_group=args.group,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
