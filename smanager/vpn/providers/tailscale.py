"""
Implements the Tailscale VPN service.
"""

from .. import VPNService
from ..registry import register_vpn
import subprocess
import json


@register_vpn("tailscale")
class TailscaleVPN(VPNService):
    """Tailscale provider that never blocks on an interactive password prompt.

    Privilege resolution is automatic by default:

    * first try the command as the current user (Tailscale *operator* mode);
    * fall back to ``sudo -n`` (non-interactive, requires NOPASSWD).

    ``sudo -n`` fails immediately instead of asking for a password, so SManager
    never leaves a half-finished operation waiting for input. Use
    ``tailscale set --operator=$USER`` or a ``/etc/sudoers.d`` entry to make the
    privileged Tailscale operations work unattended.
    """

    def __init__(self, privilege: str = "auto"):
        self.privilege = privilege if privilege in {"auto", "operator", "sudo", "none"} else "auto"
        self.connected = self.is_connected()

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------
    def _command_candidates(self) -> list[list[str]]:
        if self.privilege == "sudo":
            return [["sudo", "-n", "tailscale"]]
        if self.privilege in {"operator", "none"}:
            return [["tailscale"]]
        return [["tailscale"], ["sudo", "-n", "tailscale"]]

    def _invoke(self, args: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
        """Run a mutating ``tailscale`` command, avoiding interactive prompts.

        Tries each privilege strategy in order and raises a single RuntimeError
        with actionable context when none succeed.
        """
        errors: list[str] = []
        for prefix in self._command_candidates():
            try:
                return subprocess.run(
                    [*prefix, *args],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=timeout,
                )
            except FileNotFoundError:
                errors.append(f"{prefix[0]}: command not found")
            except subprocess.TimeoutExpired:
                errors.append(f"{' '.join(prefix)}: timed out")
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or "").strip()
                errors.append(f"{' '.join(prefix)}: {detail or f'exit code {exc.returncode}'}")

        hint = (
            "Configure unattended access with 'sudo tailscale set --operator=$USER' "
            "or a NOPASSWD sudoers entry for the tailscale binary."
        )
        raise RuntimeError(
            "Tailscale command failed (" + "; ".join(errors) + "). " + hint
        )

    # ------------------------------------------------------------------
    # VPN lifecycle
    # ------------------------------------------------------------------
    def connect(self):
        """Connect to the Tailscale VPN."""
        self._invoke(["up"])
        self.connected = self.is_connected()

    def disconnect(self):
        """Disconnect from the Tailscale VPN."""
        self._invoke(["down"])
        self.connected = self.is_connected()

    def is_connected(self) -> bool:
        """Check if the VPN is currently connected."""
        try:
            status = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                check=True,
            )
            return json.loads(status.stdout).get("BackendState", "") == "Running"
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
            return False

    def serve_https(self, port: int):
        """Serve the VPN connection over HTTPS on the specified port."""
        self._invoke(["serve", "--bg", f"--https={port}", f"http://localhost:{port}"])

    def stop_serving_https(self, port: int):
        """Stop serving the VPN connection over HTTPS on the specified port.

        Best effort and idempotent: when the port is not being served Tailscale
        reports an error, which is intentionally ignored.
        """
        try:
            self._invoke(["serve", f"--https={port}", "off"])
        except RuntimeError:
            pass

    def get_endpoint(self) -> str | None:
        """Return MagicDNS hostname or first Tailscale IP when available."""
        try:
            status = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                check=True,
            )
            parsed = json.loads(status.stdout)
            self_data = parsed.get("Self") or {}

            dns_name = self_data.get("DNSName")
            if isinstance(dns_name, str) and dns_name:
                return dns_name.rstrip(".")

            ips = self_data.get("TailscaleIPs") or []
            if ips:
                return str(ips[0])
            return None
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
            return None
