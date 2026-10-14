"""SManager privileged daemon.

The daemon concentrates privilege in a single, auditable component exposing a
narrow, validated API over a local Unix socket. The CLI is an unprivileged
client that falls back to local execution when the daemon is unavailable.
"""

from .protocol import PROTOCOL_VERSION

__all__ = ["PROTOCOL_VERSION"]
