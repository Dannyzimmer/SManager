"""Peer credential extraction and authorization for the daemon."""

from __future__ import annotations

import os
import socket
import struct
from dataclasses import dataclass
from typing import Iterable, Optional

try:  # pragma: no cover - POSIX only
    import pwd
except ImportError:  # pragma: no cover
    pwd = None


@dataclass(frozen=True)
class PeerCredentials:
    pid: int
    uid: int
    gid: int


def get_peer_credentials(connection: socket.socket) -> PeerCredentials:
    """Return the peer's ``(pid, uid, gid)`` via ``SO_PEERCRED``."""
    size = struct.calcsize("3i")
    raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, size)
    pid, uid, gid = struct.unpack("3i", raw)
    return PeerCredentials(pid=pid, uid=uid, gid=gid)


def _supplementary_gids(uid: int, primary_gid: int) -> set[int]:
    gids = {primary_gid}
    if pwd is None:
        return gids
    try:
        username = pwd.getpwuid(uid).pw_name
    except KeyError:
        return gids
    try:
        gids.update(os.getgrouplist(username, primary_gid))
    except (AttributeError, OSError):
        pass
    return gids


class Authorizer:
    """Authorize peer credentials against optional uid/gid allowlists.

    When neither ``allowed_uids`` nor ``allowed_gids`` is provided the
    authorizer accepts any peer (the socket filesystem permissions are then the
    only gate, Docker-style). Enforcing group membership is recommended and is
    configured by ``smanager daemon install``.
    """

    def __init__(
        self,
        allowed_uids: Optional[Iterable[int]] = None,
        allowed_gids: Optional[Iterable[int]] = None,
    ):
        self.allowed_uids = set(allowed_uids or [])
        self.allowed_gids = set(allowed_gids or [])

    @property
    def enforcing(self) -> bool:
        return bool(self.allowed_uids or self.allowed_gids)

    def authorize(self, creds: Optional[PeerCredentials]) -> bool:
        if creds is None:
            return not self.enforcing
        if not self.enforcing:
            return True
        if creds.uid in self.allowed_uids:
            return True
        gids = _supplementary_gids(creds.uid, creds.gid)
        return bool(gids & self.allowed_gids)
