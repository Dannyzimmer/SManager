"""Unprivileged client for the SManager daemon."""

from __future__ import annotations

import os
import socket
import time
from typing import Any, Callable, Optional

from . import protocol

DEFAULT_SOCKET_PATH = "/run/smanager/smanagerd.sock"
EventCallback = Callable[[dict], None]


class DaemonError(Exception):
    """A structured error returned by the daemon."""

    def __init__(self, code: str, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class DaemonConnectionError(Exception):
    """The daemon is unreachable or the connection dropped."""


def is_available(socket_path: str = DEFAULT_SOCKET_PATH) -> bool:
    return os.path.exists(socket_path)


class DaemonClient:
    def __init__(
        self,
        socket_path: str = DEFAULT_SOCKET_PATH,
        timeout: float = protocol.DEFAULT_TIMEOUT,
        connect_timeout: float = 5.0,
    ):
        self.socket_path = socket_path
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self._sock: Optional[socket.socket] = None
        self._rfile = None
        self._wfile = None
        self._next_id = 1
        self._handshaken = False

    # -- connection --------------------------------------------------------
    def connect(self) -> "DaemonClient":
        if self._sock is not None:
            return self
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.connect_timeout)
        try:
            sock.connect(self.socket_path)
        except OSError as exc:
            sock.close()
            raise DaemonConnectionError(f"cannot connect to daemon at {self.socket_path}: {exc}") from exc
        self._sock = sock
        self._rfile = sock.makefile("rb")
        self._wfile = sock.makefile("wb")
        self._handshaken = False
        self._hello()
        return self

    def close(self) -> None:
        for stream in (self._rfile, self._wfile):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self._rfile = None
        self._wfile = None
        self._handshaken = False

    def __enter__(self) -> "DaemonClient":
        return self.connect()

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- low level ---------------------------------------------------------
    def _ensure_connected(self) -> None:
        if self._sock is None:
            self.connect()

    def _send(self, message: dict) -> None:
        assert self._wfile is not None
        try:
            self._wfile.write(protocol.encode_message(message))
            self._wfile.flush()
        except OSError as exc:
            self.close()
            raise DaemonConnectionError(f"failed to send to daemon: {exc}") from exc

    def _read(self, deadline: float, on_event: Optional[EventCallback], request_id: int) -> Any:
        assert self._rfile is not None and self._sock is not None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DaemonError(protocol.ERR_TIMEOUT, "request timed out")
            self._sock.settimeout(remaining)
            try:
                line = self._rfile.readline(protocol.MAX_FRAME_BYTES + 1)
            except (socket.timeout, TimeoutError) as exc:
                raise DaemonError(protocol.ERR_TIMEOUT, "request timed out") from exc
            except OSError as exc:
                self.close()
                raise DaemonConnectionError(f"connection to daemon lost: {exc}") from exc

            if not line:
                self.close()
                raise DaemonConnectionError("daemon closed the connection")

            try:
                message = protocol.decode_message(line)
            except protocol.ProtocolError as exc:
                raise DaemonError(exc.code, exc.message) from exc

            if "event" in message:
                if on_event is not None:
                    on_event(message["event"])
                continue
            if "error" in message:
                # Errors may arrive with id=None (e.g. unauthorized before any
                # request is parsed); surface them instead of waiting forever.
                if message.get("id") in (None, request_id):
                    error = message.get("error") or {}
                    raise DaemonError(
                        error.get("code", protocol.ERR_INTERNAL),
                        error.get("message", "daemon error"),
                        error.get("details"),
                    )
                continue
            if message.get("id") != request_id:
                continue
            if message.get("ok"):
                return message.get("result")

    def _call(
        self,
        method: str,
        params: Optional[dict],
        on_event: Optional[EventCallback],
        timeout: Optional[float],
    ) -> Any:
        self._ensure_connected()
        request_id = self._next_id
        self._next_id += 1
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        self._send(protocol.make_request(request_id, method, params))
        return self._read(deadline, on_event, request_id)

    def _hello(self) -> None:
        result = self._call("hello", {"protocol": protocol.PROTOCOL_VERSION}, None, self.connect_timeout)
        self._handshaken = True
        return result

    # -- public API --------------------------------------------------------
    def request(
        self,
        method: str,
        params: Optional[dict] = None,
        on_event: Optional[EventCallback] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        return self._call(method, params, on_event, timeout)

    def ping(self) -> bool:
        return bool(self.request("daemon.ping").get("pong"))

    def version(self) -> dict:
        return self.request("daemon.version")

    def list_services(self) -> list[dict]:
        return self.request("catalog.list").get("services", [])

    def info(self, service_id: str) -> dict:
        return self.request("service.info", {"id": service_id})

    def status(self, service_id: str, check_updates: bool = False) -> dict:
        return self.request("service.status", {"id": service_id, "check_updates": check_updates})

    def action(
        self,
        service_id: str,
        action: str,
        dry_run: bool = False,
        on_event: Optional[EventCallback] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        return self.request(
            "service.action",
            {"id": service_id, "action": action, "dry_run": dry_run},
            on_event=on_event,
            timeout=timeout,
        )

    def group_action(self, group_name: str, action: str, dry_run: bool = False,
                     on_event: Optional[EventCallback] = None, timeout: Optional[float] = None) -> dict:
        return self.request(
            "group.action",
            {"group": group_name, "action": action, "dry_run": dry_run},
            on_event=on_event,
            timeout=timeout,
        )

    def dependency_action(self, dependency_name: str, action: str, dry_run: bool = False,
                          on_event: Optional[EventCallback] = None, timeout: Optional[float] = None) -> dict:
        return self.request(
            "dependency.action",
            {"dependency": dependency_name, "action": action, "dry_run": dry_run},
            on_event=on_event,
            timeout=timeout,
        )

    def all_action(self, action: str, dry_run: bool = False,
                   on_event: Optional[EventCallback] = None, timeout: Optional[float] = None) -> dict:
        return self.request(
            "all.action",
            {"action": action, "dry_run": dry_run},
            on_event=on_event,
            timeout=timeout,
        )
