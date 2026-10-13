"""
The bass manager for SDV2 services.
It extends the BaseManager with SDV2-specific logic, such as handling the SDConfig
file and integrating with VPN services.
"""

import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

try:
    from packaging.version import InvalidVersion, Version
except ImportError:  # pragma: no cover - packaging is a declared dependency
    InvalidVersion = ValueError  # type: ignore[assignment,misc]
    Version = None  # type: ignore[assignment]

from . import BaseManager
from ..datatypes import Service, UpdateInfo
from ..vpn import VPNService

GITHUB_API = "https://api.github.com/repos/{repo}/releases/latest"
DEFAULT_CHECK_TIMEOUT = 5

FLOATING_IMAGE_TAGS = {
    "latest",
    "stable",
    "edge",
    "nightly",
    "dev",
    "main",
    "master",
}

OCI_VERSION_LABELS = ("org.opencontainers.image.version", "version")

# Sentinel: ``available`` was not decided by the strategy, so it should be
# derived from the version strings.
_UNSET = object()


@dataclass
class _VersionCheck:
    """Internal strategy result feeding ``UpdateInfo``."""

    current: str | None = None
    latest: str | None = None
    available: object = _UNSET
    current_kind: str | None = None
    latest_kind: str | None = None
    current_digest: str | None = None
    latest_digest: str | None = None


class BaseSDV2Manager(BaseManager):
    def __init__(self, service: Service, vpn: VPNService, restart_delay: int = 5, event_dispatcher=None):
        super().__init__(service, event_dispatcher=event_dispatcher)
        self.service = service
        self.vpn = vpn
        self.restart_delay = restart_delay
        self.systemd_privilege = "auto"

    def enable(self):
        """Change the JSON config to set the service as active."""
        self._emit_event(
            scope="service",
            action="enable",
            phase="before",
            service_id=self.get_id(),
        )
        try:
            self.service.metadata.active = True
            output_path = os.path.join(self.service.service_abspath, self.service.metadata_filename)
            self.service.metadata.write_to_json(output_path)
        except Exception as exc:
            self._emit_event(
                scope="service",
                action="enable",
                phase="failed",
                service_id=self.get_id(),
                error=exc,
            )
            raise
        self._emit_event(
            scope="service",
            action="enable",
            phase="after",
            service_id=self.get_id(),
            payload={"active": True},
        )

    def disable(self):
        """Change the JSON config to set the service as inactive."""
        self._emit_event(
            scope="service",
            action="disable",
            phase="before",
            service_id=self.get_id(),
        )
        try:
            self.service.metadata.active = False
            output_path = os.path.join(self.service.service_abspath, self.service.metadata_filename)
            self.service.metadata.write_to_json(output_path)
        except Exception as exc:
            self._emit_event(
                scope="service",
                action="disable",
                phase="failed",
                service_id=self.get_id(),
                error=exc,
            )
            raise
        self._emit_event(
            scope="service",
            action="disable",
            phase="after",
            service_id=self.get_id(),
            payload={"active": False},
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self):
        self._emit_event(
            scope="service",
            action="start",
            phase="before",
            service_id=self.get_id(),
        )
        if not self.service.metadata.active:
            self._emit_event(
                scope="service",
                action="start",
                phase="skipped",
                service_id=self.get_id(),
                message="Service is inactive.",
            )
            return
        try:
            if not self._run_script("start"):
                self._start_runtime()
            self._after_runtime_started()
        except Exception as exc:
            self._emit_event(
                scope="service",
                action="start",
                phase="failed",
                service_id=self.get_id(),
                error=exc,
            )
            raise
        self._emit_event(
            scope="service",
            action="start",
            phase="after",
            service_id=self.get_id(),
        )

    def stop(self):
        self._emit_event(
            scope="service",
            action="stop",
            phase="before",
            service_id=self.get_id(),
        )
        try:
            self._ensure_https_stopped()
            if not self._run_script("stop"):
                self._stop_runtime()
        except Exception as exc:
            self._emit_event(
                scope="service",
                action="stop",
                phase="failed",
                service_id=self.get_id(),
                error=exc,
            )
            raise
        self._emit_event(
            scope="service",
            action="stop",
            phase="after",
            service_id=self.get_id(),
        )

    def restart(self):
        """Restart the service.

        A ``scripts.restart`` override fully owns the stop/start sequence; SManager
        still re-establishes the VPN HTTPS serve afterwards. Without an override the
        default is ``stop`` + ``start`` (which honours the start/stop overrides).
        """
        self._emit_event(
            scope="service",
            action="restart",
            phase="before",
            service_id=self.get_id(),
        )
        stop_warning: str | None = None
        try:
            if self._run_script("restart"):
                if self._serve_https_enabled():
                    self._wait_for_webui()
                    self._ensure_https_serving()
            else:
                try:
                    self.stop()
                except Exception as stop_exc:  # keep going, but do not hide it
                    stop_warning = str(stop_exc)
                try:
                    self.start()
                except Exception as start_exc:
                    if stop_warning:
                        raise RuntimeError(
                            f"restart failed: stop error: {stop_warning}; "
                            f"start error: {start_exc}"
                        ) from start_exc
                    raise
        except Exception as exc:
            self._emit_event(
                scope="service",
                action="restart",
                phase="failed",
                service_id=self.get_id(),
                error=exc,
            )
            raise
        self._emit_event(
            scope="service",
            action="restart",
            phase="after",
            service_id=self.get_id(),
            payload={"stop_warning": stop_warning} if stop_warning else {},
        )

    def update(self, dry_run: bool = False):
        """Update the service to the latest available version.

        Resolution order:

        1. ``scripts.update`` (owns the whole update/restart sequence);
        2. the strategy from the ``update`` metadata section (explicit), or the
           runtime default (Docker) / opt-in heuristics (``strategy: auto``).

        Git and Composer strategies restart the service afterwards so the new
        code takes effect. ``dry_run`` only reports the commands that would run.
        """
        self._emit_event(
            scope="service",
            action="update",
            phase="before",
            service_id=self.get_id(),
            payload={"dry_run": dry_run},
        )
        if not self.service.metadata.active:
            self._emit_event(
                scope="service",
                action="update",
                phase="skipped",
                service_id=self.get_id(),
                message="Service is inactive.",
            )
            return

        commands: list[list[str]] = []
        try:
            strategy = self._resolve_update_strategy()
            needs_restart = strategy in {"git", "composer"}

            if strategy == "script":
                commands = [self._script_argv("update")]
                if not dry_run:
                    self._run_script("update")
            else:
                planned = self._update_commands(strategy)
                commands = [command for command, _ in planned]
                if not dry_run:
                    for command, cwd in planned:
                        self._process_run(command, cwd=cwd)
                    if needs_restart:
                        # restart already re-establishes the VPN HTTPS serve.
                        self.restart()

            if not dry_run and not needs_restart and self._serve_https_enabled():
                self._wait_for_webui()
                self._ensure_https_serving()
        except Exception as exc:
            self._emit_event(
                scope="service",
                action="update",
                phase="failed",
                service_id=self.get_id(),
                error=exc,
            )
            raise

        self._emit_event(
            scope="service",
            action="update",
            phase="after",
            service_id=self.get_id(),
            payload={
                "strategy": strategy,
                "dry_run": dry_run,
                "commands": commands,
            },
        )

    # ------------------------------------------------------------------
    # Runtime hooks (implemented by concrete managers)
    # ------------------------------------------------------------------
    def _start_runtime(self):
        raise NotImplementedError("_start_runtime must be implemented by subclasses.")

    def _stop_runtime(self):
        raise NotImplementedError("_stop_runtime must be implemented by subclasses.")

    def _after_runtime_started(self):
        """Ensure the VPN HTTPS serve is active once the runtime has started."""
        if not self._serve_https_enabled():
            return
        self._wait_for_webui()
        self._ensure_https_serving()

    # ------------------------------------------------------------------
    # Scripts
    # ------------------------------------------------------------------
    def _script_value(self, action: str) -> str | None:
        scripts = self.service.metadata.scripts
        if scripts is None:
            return None
        value = getattr(scripts, action, None)
        if value is None or not str(value).strip():
            return None
        return str(value).strip()

    def _resolve_script_path(self, value: str) -> str:
        expanded = os.path.expanduser(value)
        if not os.path.isabs(expanded):
            expanded = os.path.join(self.service.service_abspath, expanded)
        return os.path.abspath(expanded)

    def _script_argv(self, action: str) -> list[str] | None:
        """Return the argv used to run the script for *action*, or None."""
        value = self._script_value(action)
        if value is None:
            return None
        interpreter = shutil.which("bash") or shutil.which("sh") or "/bin/sh"
        return [interpreter, self._resolve_script_path(value)]

    def _run_script(self, action: str) -> bool:
        """Run the configured script for *action*.

        Returns False when no script is configured. Raises a RuntimeError with the
        captured output when the script exits with a non-zero status.
        """
        argv = self._script_argv(action)
        if argv is None:
            return False

        script_path = argv[1]
        if not os.path.isfile(script_path):
            raise RuntimeError(
                f"Script for '{action}' not found: {script_path}"
            )

        scripts = self.service.metadata.scripts

        run_env = os.environ.copy()
        if scripts is not None and scripts.env:
            run_env.update({str(key): str(val) for key, val in scripts.env.items()})

        cwd = self.service.service_abspath
        if scripts is not None and scripts.working_dir:
            candidate = os.path.expanduser(scripts.working_dir)
            if not os.path.isabs(candidate):
                candidate = os.path.join(self.service.service_abspath, candidate)
            cwd = candidate

        try:
            subprocess.run(
                argv,
                capture_output=True,
                text=True,
                check=True,
                cwd=cwd,
                env=run_env,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise RuntimeError(
                f"Script '{action}' failed for service '{self.get_id()}' "
                f"({script_path}): {detail or f'exit code {exc.returncode}'}"
            ) from exc

        return True

    def _script_status(self) -> str | None:
        """Return the status reported by a ``scripts.status`` override.

        Returns None when no status script is configured. The exit code drives the
        result: 0 -> "running", anything else -> "stopped", unusable -> "unknown".
        """
        value = self._script_value("status")
        if value is None:
            return None

        script_path = self._resolve_script_path(value)
        if not os.path.isfile(script_path):
            return "unknown"

        scripts = self.service.metadata.scripts
        interpreter = shutil.which("bash") or shutil.which("sh") or "/bin/sh"

        run_env = os.environ.copy()
        if scripts is not None and scripts.env:
            run_env.update({str(key): str(val) for key, val in scripts.env.items()})

        cwd = self.service.service_abspath
        if scripts is not None and scripts.working_dir:
            candidate = os.path.expanduser(scripts.working_dir)
            if not os.path.isabs(candidate):
                candidate = os.path.join(self.service.service_abspath, candidate)
            cwd = candidate

        try:
            result = subprocess.run(
                [interpreter, script_path],
                capture_output=True,
                text=True,
                check=False,
                cwd=cwd,
                env=run_env,
            )
        except OSError:
            return "unknown"

        return "running" if result.returncode == 0 else "stopped"

    # ------------------------------------------------------------------
    # Update strategies
    # ------------------------------------------------------------------
    def _update_path(self) -> str:
        """Resolve the working directory used by git/composer/command strategies."""
        update = self.service.metadata.update
        candidates: list[str] = []
        if update and update.path:
            candidates.append(update.path)

        local = self.service.metadata.local
        if local and local.installation_path:
            candidates.append(local.installation_path)

        php = self.service.metadata.php
        if php and php.working_dir:
            candidates.append(php.working_dir)

        candidates.append(self.service.service_abspath)

        for candidate in candidates:
            expanded = os.path.expanduser(str(candidate))
            if not os.path.isabs(expanded):
                expanded = os.path.join(self.service.service_abspath, expanded)
            if os.path.isdir(expanded):
                return os.path.abspath(expanded)
        return self.service.service_abspath

    def _detect_update_strategy(self) -> str | None:
        path = self._update_path()
        if os.path.isdir(os.path.join(path, ".git")):
            return "git"
        if os.path.isfile(os.path.join(path, "composer.json")):
            return "composer"
        return None

    def _resolve_update_strategy(self) -> str:
        if self._script_value("update") is not None:
            return "script"

        update = self.service.metadata.update
        explicit = update.strategy if update else None
        runtime_type = self.service.metadata.runtime.type

        if explicit in (None, "auto"):
            if runtime_type == "docker":
                return "docker"
            if explicit == "auto" and update is not None:
                detected = self._detect_update_strategy()
                if detected:
                    return detected
                raise RuntimeError(
                    "update.strategy 'auto' could not detect a git repository or "
                    f"composer.json in '{self._update_path()}'. Set 'update.path' or "
                    "use an explicit strategy."
                )
            raise RuntimeError(
                f"No default update strategy for runtime '{runtime_type}'. Define "
                "'scripts.update' or an 'update' section (strategy: auto, git, "
                "composer, command)."
            )

        if explicit == "none":
            raise RuntimeError("Update is disabled (update.strategy='none').")
        if explicit == "docker" and runtime_type != "docker":
            raise RuntimeError("update.strategy 'docker' requires runtime.type 'docker'.")
        return explicit

    def _update_commands(self, strategy: str) -> list[tuple[list[str], str | None]]:
        """Return the (command, cwd) pairs to run for *strategy*."""
        if strategy == "docker":
            return [(command, None) for command in self._update_docker_commands()]
        if strategy == "git":
            return [(command, None) for command in self._update_git_commands()]
        if strategy == "composer":
            return [(command, None) for command in self._update_composer_commands()]
        if strategy == "command":
            update = self.service.metadata.update
            command = shlex.split(update.command) if update and update.command else []
            if not command:
                raise RuntimeError("update.strategy 'command' requires 'update.command'.")
            return [(command, self._update_path())]
        raise RuntimeError(f"Unsupported update strategy: {strategy}")

    def _update_docker_commands(self) -> list[list[str]]:
        raise RuntimeError(
            "update.strategy 'docker' requires runtime.type 'docker' with "
            "'docker.compose_file'."
        )

    def _update_git_commands(self) -> list[list[str]]:
        path = self._update_path()
        if not os.path.isdir(os.path.join(path, ".git")):
            raise RuntimeError(
                f"update.strategy 'git' but '{path}' is not a git repository."
            )
        command = ["git", "-C", path, "pull"]
        update = self.service.metadata.update
        if update and update.branch:
            command += ["origin", str(update.branch)]
        if update and update.args:
            command += [str(arg) for arg in update.args]
        return [command]

    def _update_composer_commands(self) -> list[list[str]]:
        path = self._update_path()
        if not os.path.isfile(os.path.join(path, "composer.json")):
            raise RuntimeError(
                f"update.strategy 'composer' but no composer.json found in '{path}'."
            )
        command = ["composer", "--working-dir", path, "update", "--no-interaction"]
        update = self.service.metadata.update
        if update and update.args:
            command += [str(arg) for arg in update.args]
        return [command]

    def _process_run(
        self,
        command: list[str],
        cwd: str | None = None,
    ) -> subprocess.CompletedProcess:
        """Run a command for the update strategies with normalised errors."""
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                cwd=cwd,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise RuntimeError(
                f"Command failed ({' '.join(command)}): "
                f"{detail or f'exit code {exc.returncode}'}"
            ) from exc
        except FileNotFoundError as exc:
            raise RuntimeError(f"Command not found: {command[0]}") from exc

    # ------------------------------------------------------------------
    # Version checking
    # ------------------------------------------------------------------
    def check_update(self) -> UpdateInfo | None:
        """Return update availability for this service.

        Returns None when the service is not configured for version checking
        (no ``version`` section and no ``scripts.check_update``). Errors are
        captured in ``UpdateInfo.error`` so ``status`` never fails.
        """
        version = self.service.metadata.version
        if version is None and self._script_value("check_update") is None:
            return None

        strategy: str | None = None
        try:
            strategy = self._resolve_version_strategy()
            result = self._evaluate_version_strategy(strategy)
            available = (
                self._compare_versions(result.current, result.latest)
                if result.available is _UNSET
                else result.available
            )
            return UpdateInfo(
                available=available,
                current=result.current,
                latest=result.latest,
                source=strategy,
                current_kind=result.current_kind,
                latest_kind=result.latest_kind,
                current_digest=result.current_digest,
                latest_digest=result.latest_digest,
            )
        except Exception as exc:  # noqa: BLE001 - status must not fail
            return UpdateInfo(source=strategy, error=str(exc))

    @property
    def _check_timeout(self) -> float:
        try:
            return float(os.environ.get("SMANAGER_CHECK_TIMEOUT", DEFAULT_CHECK_TIMEOUT))
        except (TypeError, ValueError):
            return float(DEFAULT_CHECK_TIMEOUT)

    def _resolve_version_strategy(self) -> str:
        if self._script_value("check_update") is not None:
            return "script"

        version = self.service.metadata.version
        latest = version.latest if version else None
        explicit = latest.strategy if latest else None
        if explicit and explicit != "auto":
            return explicit

        if self.service.metadata.runtime.type == "docker":
            return "docker"
        if self._github_repo() is not None:
            return "github"
        detected = self._detect_update_strategy()
        if detected:
            return detected
        raise RuntimeError(
            "Could not auto-detect a version source. Set 'version.latest.strategy' "
            "or provide 'scripts.check_update'."
        )

    def _evaluate_version_strategy(self, strategy: str) -> _VersionCheck:
        version = self.service.metadata.version
        latest = version.latest if version else None
        regex = version.regex if version else None

        if strategy == "docker":
            return self._docker_version_info()
        if strategy == "composer":
            return self._composer_version_info()
        if strategy == "git":
            return self._git_version_info(latest)

        current = self._current_version(strategy)

        if strategy == "script":
            latest_version = self._extract_version(self._run_script_output("check_update"), regex)
        elif strategy == "command":
            if not latest or not latest.command:
                raise RuntimeError("version.latest.strategy 'command' requires 'command'.")
            latest_version = self._extract_version(self._run_check_command(latest.command), regex)
        elif strategy == "github":
            repo = self._github_repo()
            if not repo:
                raise RuntimeError(
                    "version.latest.strategy 'github' needs 'repo' or a github git remote."
                )
            latest_version = self._extract_version(self._fetch_github_latest(repo), regex)
        elif strategy == "package":
            if not latest:
                raise RuntimeError("version.latest.strategy 'package' requires configuration.")
            return self._package_version_info(latest)
        else:
            raise RuntimeError(f"Unsupported version strategy: {strategy}")

        return _VersionCheck(current=current, latest=latest_version)

    def _current_version(self, strategy: str) -> str | None:
        version = self.service.metadata.version
        if version and version.current_command:
            text = self._run_check_command(version.current_command)
            return self._extract_version(text, version.regex)

        path = self._update_path()
        if os.path.isdir(os.path.join(path, ".git")):
            tag = self._git_output(path, ["describe", "--tags", "--abbrev=0"])
            if tag:
                return tag
            return self._git_output(path, ["rev-parse", "--short", "HEAD"])
        return None

    @staticmethod
    def _extract_version(text: str | None, regex: str | None) -> str | None:
        if not text:
            return None
        cleaned = text.strip()
        if not cleaned:
            return None
        if regex:
            match = re.search(regex, cleaned, re.MULTILINE)
            if not match:
                return None
            value = match.group(1) if match.groups() else match.group(0)
            return value.strip()
        match = re.search(r"v?\d+(?:\.\d+)+", cleaned)
        if match:
            return match.group(0)
        return cleaned.splitlines()[0].strip()

    @staticmethod
    def _compare_versions(current: str | None, latest: str | None) -> bool | None:
        if latest is None or current is None:
            return None
        current_text = str(current).strip()
        latest_text = str(latest).strip()
        if current_text == latest_text:
            return False
        # Git SHAs may differ in length (short vs full) for the same commit.
        if re.fullmatch(r"[0-9a-f]{7,40}", current_text) and re.fullmatch(r"[0-9a-f]{7,40}", latest_text):
            return not (current_text.startswith(latest_text) or latest_text.startswith(current_text))
        if Version is None:
            return True
        try:
            normalized_current = Version(str(current).strip().lstrip("vV"))
            normalized_latest = Version(str(latest).strip().lstrip("vV"))
            return normalized_latest > normalized_current
        except InvalidVersion:
            return True
        except Exception:
            return True

    @staticmethod
    def _highest_version(values: list[str]) -> str | None:
        best: str | None = None
        best_parsed = None
        for value in values:
            if Version is None:
                return best or (values[0] if values else None)
            try:
                parsed = Version(str(value).strip().lstrip("vV"))
            except InvalidVersion:
                continue
            if best_parsed is None or parsed > best_parsed:
                best_parsed = parsed
                best = value
        return best or (values[0] if values else None)

    # --- command/script helpers -------------------------------------
    def _run_check_command(self, command: str) -> str:
        argv = shlex.split(command)
        if not argv:
            raise RuntimeError("Empty version command.")
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                check=True,
                cwd=self._update_path(),
                timeout=self._check_timeout,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise RuntimeError(
                f"Version command failed ({command}): {detail or f'exit code {exc.returncode}'}"
            ) from exc
        except FileNotFoundError as exc:
            raise RuntimeError(f"Command not found: {argv[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Version command timed out: {command}") from exc
        return result.stdout.strip()

    def _run_script_output(self, action: str) -> str:
        argv = self._script_argv(action)
        if argv is None:
            raise RuntimeError(f"No '{action}' script configured.")
        scripts = self.service.metadata.scripts
        run_env = os.environ.copy()
        if scripts is not None and scripts.env:
            run_env.update({str(key): str(val) for key, val in scripts.env.items()})
        cwd = self.service.service_abspath
        if scripts is not None and scripts.working_dir:
            candidate = os.path.expanduser(scripts.working_dir)
            if not os.path.isabs(candidate):
                candidate = os.path.join(self.service.service_abspath, candidate)
            cwd = candidate
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                check=True,
                cwd=cwd,
                env=run_env,
                timeout=self._check_timeout,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise RuntimeError(
                f"Script '{action}' failed: {detail or f'exit code {exc.returncode}'}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Script '{action}' timed out.") from exc
        return result.stdout.strip()

    def _cmd_stdout(self, args: list[str], timeout: float | None = None) -> str | None:
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout or self._check_timeout,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    # --- git helpers ------------------------------------------------
    def _git_output(self, path: str, args: list[str]) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", path, *args],
                capture_output=True,
                text=True,
                check=True,
                timeout=self._check_timeout,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        return result.stdout.strip() or None

    def _git_remote_tags(self, path: str) -> list[str]:
        try:
            result = subprocess.run(
                ["git", "-C", path, "ls-remote", "--tags", "--refs", "origin"],
                capture_output=True,
                text=True,
                check=True,
                timeout=self._check_timeout,
            )
        except (subprocess.SubprocessError, OSError):
            return []
        tags: list[str] = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].startswith("refs/tags/"):
                tags.append(parts[1][len("refs/tags/"):])
        return tags

    def _git_fetch(self, path: str, branch: str | None) -> None:
        command = ["git", "-C", path, "fetch", "--quiet", "origin"]
        if branch:
            command.append(branch)
        try:
            subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=max(self._check_timeout, 15),
            )
        except (subprocess.SubprocessError, OSError):
            pass

    def _git_count(self, path: str, revision_range: str) -> int | None:
        output = self._git_output(path, ["rev-list", "--count", revision_range])
        if not output:
            return None
        try:
            return int(output)
        except ValueError:
            return None

    def _git_version_info(self, latest) -> _VersionCheck:
        path = self._update_path()
        if not os.path.isdir(os.path.join(path, ".git")):
            raise RuntimeError(
                f"version strategy 'git' but '{path}' is not a git repository."
            )

        local_tag = self._git_output(path, ["describe", "--tags", "--abbrev=0"])
        remote_tags = self._git_remote_tags(path)
        if local_tag and remote_tags:
            return _VersionCheck(current=local_tag, latest=self._highest_version(remote_tags))

        branch = latest.branch if latest and latest.branch else None
        if not branch:
            upstream = self._git_output(
                path, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]
            )
            if upstream and "/" in upstream:
                branch = upstream.split("/", 1)[1]
        if not branch:
            branch = self._git_output(path, ["rev-parse", "--abbrev-ref", "HEAD"])

        self._git_fetch(path, branch)
        local_sha = self._git_output(path, ["rev-parse", "HEAD"])
        remote_sha = self._git_output(path, ["rev-parse", "FETCH_HEAD"])
        if not local_sha or not remote_sha:
            return _VersionCheck(
                current=local_sha[:12] if local_sha else None,
                latest=remote_sha[:12] if remote_sha else None,
            )
        if local_sha == remote_sha:
            return _VersionCheck(current=local_sha[:12], latest=remote_sha[:12], available=False)

        remote_ahead = self._git_count(path, "HEAD..FETCH_HEAD")
        local_ahead = self._git_count(path, "FETCH_HEAD..HEAD")
        override: bool | None = None
        if remote_ahead is not None and local_ahead is not None:
            override = remote_ahead > 0
        return _VersionCheck(current=local_sha[:12], latest=remote_sha[:12], available=override)

    @staticmethod
    def _parse_github_repo(url: str) -> str | None:
        if not url:
            return None
        match = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", url.strip())
        if not match:
            return None
        return f"{match.group(1)}/{match.group(2)}"

    def _github_repo(self) -> str | None:
        version = self.service.metadata.version
        latest = version.latest if version else None
        if latest and latest.repo:
            return str(latest.repo).strip()
        path = self._update_path()
        if not os.path.isdir(os.path.join(path, ".git")):
            return None
        url = self._git_output(path, ["remote", "get-url", "origin"])
        return self._parse_github_repo(url or "")

    def _fetch_github_latest(self, repo: str) -> str:
        request = urllib.request.Request(
            GITHUB_API.format(repo=repo),
            headers={"Accept": "application/vnd.github+json", "User-Agent": "smanager"},
        )
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=self._check_timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"GitHub API error for '{repo}': HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"GitHub API request failed for '{repo}': {exc}") from exc
        tag = payload.get("tag_name") or payload.get("name")
        if not tag:
            raise RuntimeError(f"GitHub API returned no tag for '{repo}'.")
        return str(tag)

    # --- composer ---------------------------------------------------
    def _composer_version_info(self) -> _VersionCheck:
        path = self._update_path()
        if not os.path.isfile(os.path.join(path, "composer.json")):
            raise RuntimeError(
                f"version strategy 'composer' but no composer.json found in '{path}'."
            )
        command = [
            "composer", "--working-dir", path, "outdated",
            "--direct", "--format=json", "--no-interaction",
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=max(self._check_timeout, 30),
            )
        except FileNotFoundError as exc:
            raise RuntimeError("composer executable not found.") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("composer outdated timed out.") from exc

        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"Could not parse composer outdated output: {detail}") from exc

        outdated: list[str] = []
        for package in payload.get("installed") or []:
            name = package.get("name")
            current = package.get("version")
            latest = package.get("latest")
            status = package.get("latest-status")
            if latest and status not in (None, "up-to-date") and str(current) != str(latest):
                outdated.append(f"{name} {current}->{latest}")
        if outdated:
            return _VersionCheck(current="; ".join(outdated), latest="updates available", available=True)
        return _VersionCheck(current="up-to-date", latest="up-to-date", available=False)

    # --- docker -----------------------------------------------------
    def _docker_version_info(self) -> _VersionCheck:
        docker = self.service.metadata.docker
        if self.service.metadata.runtime.type != "docker" or not docker or not docker.compose_file:
            raise RuntimeError("version strategy 'docker' requires docker.compose_file.")
        compose_path = os.path.join(self.service.service_abspath, docker.compose_file)
        images = self._docker_compose_images(compose_path)
        if not images:
            raise RuntimeError("Could not determine images from the compose file.")

        outdated: list[str] = []
        current_values: list[str] = []
        current_kinds: list[str] = []
        current_digests: list[str] = []
        latest_values: list[str] = []
        latest_kinds: list[str] = []
        latest_digests: list[str] = []
        missing_local = False

        for image in images:
            local_digest = self._docker_local_digest(image)
            remote_digest = self._docker_remote_digest(image)

            local_value, local_kind = self._docker_local_version(image, local_digest)
            if local_value:
                current_values.append(local_value)
            if local_kind:
                current_kinds.append(local_kind)
            if local_digest:
                current_digests.append(local_digest)
            elif remote_digest:
                missing_local = True

            remote_value, remote_kind = self._docker_remote_version(image, remote_digest)
            if remote_value:
                latest_values.append(remote_value)
            if remote_kind:
                latest_kinds.append(remote_kind)
            if remote_digest:
                latest_digests.append(remote_digest)

            if local_digest and remote_digest and local_digest != remote_digest:
                outdated.append(image)

        if not latest_digests or missing_local:
            available: bool | None = None
        else:
            available = bool(outdated)

        return _VersionCheck(
            current=", ".join(current_values) or None,
            latest=", ".join(latest_values) or None,
            available=available,
            current_kind=self._unanimous_kind(current_kinds, len(images)),
            latest_kind=self._unanimous_kind(latest_kinds, len(images)),
            current_digest=", ".join(current_digests) or None,
            latest_digest=", ".join(latest_digests) or None,
        )

    @staticmethod
    def _unanimous_kind(kinds: list[str], expected: int) -> str | None:
        """Return the shared kind when every image agrees, else None."""
        if not kinds or len(kinds) != expected:
            return None
        first = kinds[0]
        return first if all(kind == first for kind in kinds) else None

    def _docker_local_version(self, image: str, local_digest: str | None) -> tuple[str | None, str | None]:
        for label in OCI_VERSION_LABELS:
            value = self._docker_image_label(image, label)
            if value:
                return value, "version"
        tag = self._image_tag(image)
        if tag and self._looks_like_version(tag) and not self._is_floating_tag(tag):
            return tag, "tag"
        if local_digest:
            return local_digest, "digest"
        return None, None

    def _docker_remote_version(self, image: str, remote_digest: str | None) -> tuple[str | None, str | None]:
        value = self._docker_remote_label(image)
        if value:
            return value, "version"
        if remote_digest:
            return remote_digest, "digest"
        return None, None

    def _docker_image_label(self, image: str, label: str) -> str | None:
        output = self._cmd_stdout(
            [
                "docker", "image", "inspect", image,
                "--format", f'{{{{ index .Config.Labels "{label}" }}}}',
            ],
            timeout=max(self._check_timeout, 15),
        )
        if not output:
            return None
        value = output.strip()
        if value in {"", "<no value>", "null", "{}"}:
            return None
        return value

    def _docker_remote_label(self, image: str) -> str | None:
        timeout = max(self._check_timeout, 20)
        payload = None
        if shutil.which("regctl"):
            payload = self._load_json(self._cmd_stdout(["regctl", "image", "config", image], timeout=timeout))
        if payload is None and shutil.which("crane"):
            payload = self._load_json(self._cmd_stdout(["crane", "config", image], timeout=timeout))
        if payload is None and shutil.which("skopeo"):
            payload = self._load_json(
                self._cmd_stdout(["skopeo", "inspect", f"docker://{image}"], timeout=timeout)
            )
        if payload is None:
            return None
        return self._extract_oci_label(payload)

    @staticmethod
    def _load_json(output: str | None):
        if not output:
            return None
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _extract_oci_label(payload) -> str | None:
        if not isinstance(payload, dict):
            return None
        candidates = []
        config = payload.get("config")
        if isinstance(config, dict):
            candidates.append(config.get("Labels"))
        candidates.append(payload.get("Labels"))
        for labels in candidates:
            if isinstance(labels, dict):
                for key in OCI_VERSION_LABELS:
                    value = labels.get(key)
                    if value:
                        return str(value)
        return None

    @staticmethod
    def _image_tag(image: str) -> str | None:
        ref = image.strip()
        if not ref or "@" in ref:
            return None
        last = ref.rsplit("/", 1)[-1]
        if ":" in last:
            tag = last.rsplit(":", 1)[1]
            return tag or None
        return None

    @staticmethod
    def _looks_like_version(tag: str) -> bool:
        return bool(re.fullmatch(r"v?\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.-]+)?", tag.strip()))

    @staticmethod
    def _is_floating_tag(tag: str) -> bool:
        return tag.strip().lower() in FLOATING_IMAGE_TAGS

    def _docker_compose_images(self, compose_path: str) -> list[str]:
        output = self._cmd_stdout(
            ["docker", "compose", "-f", compose_path, "config", "--images"],
            timeout=max(self._check_timeout, 15),
        )
        if not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]

    def _docker_local_digest(self, image: str) -> str | None:
        output = self._cmd_stdout(
            ["docker", "image", "inspect", image, "--format", "{{json .RepoDigests}}"],
            timeout=max(self._check_timeout, 15),
        )
        if not output:
            return None
        try:
            digests = json.loads(output)
        except json.JSONDecodeError:
            return None
        if not digests:
            return None
        return str(digests[0]).split("@")[-1]

    def _docker_remote_digest(self, image: str) -> str | None:
        if shutil.which("docker"):
            output = self._cmd_stdout(
                ["docker", "buildx", "imagetools", "inspect", image, "--format", "{{.Manifest.Digest}}"],
                timeout=max(self._check_timeout, 20),
            )
            if output:
                return output
        if shutil.which("regctl"):
            output = self._cmd_stdout(["regctl", "image", "digest", image], timeout=max(self._check_timeout, 20))
            if output:
                return output
        if shutil.which("crane"):
            output = self._cmd_stdout(["crane", "digest", image], timeout=max(self._check_timeout, 20))
            if output:
                return output
        return None

    # --- package managers -------------------------------------------
    def _package_version_info(self, latest) -> _VersionCheck:
        manager = latest.package_manager
        package = latest.package
        if manager == "apt":
            output = self._cmd_stdout(["apt-cache", "policy", package])
            if output is None:
                raise RuntimeError("apt-cache not available.")
            current = re.search(r"Installed:\s*(\S+)", output)
            candidate = re.search(r"Candidate:\s*(\S+)", output)
            current_v = current.group(1) if current else None
            latest_v = candidate.group(1) if candidate else None
            return _VersionCheck(current=current_v, latest=latest_v)
        if manager == "pacman":
            current_v = self._cmd_stdout(["pacman", "-Q", package])
            current_v = current_v.split()[-1] if current_v else None
            upgradable = self._cmd_stdout(["pacman", "-Qu", package])
            latest_v = upgradable.split()[-1] if upgradable else current_v
            return _VersionCheck(current=current_v, latest=latest_v)
        if manager == "dnf":
            upgradable = self._cmd_stdout(["dnf", "-q", "check-update", package])
            current_v = self._cmd_stdout(["rpm", "-q", "--qf", "%{VERSION}", package])
            if upgradable:
                parts = upgradable.split()
                latest_v = parts[1] if len(parts) > 1 else None
                return _VersionCheck(current=current_v, latest=latest_v, available=True)
            return _VersionCheck(current=current_v, latest=current_v, available=False)
        if manager == "flatpak":
            info = self._cmd_stdout(["flatpak", "remote-info", "flathub", package])
            if info is None:
                raise RuntimeError("flatpak remote-info failed.")
            latest_match = re.search(r"^\s*Version:\s*(.+)$", info, re.MULTILINE)
            latest_v = latest_match.group(1).strip() if latest_match else None
            return _VersionCheck(latest=latest_v)
        raise RuntimeError(f"Unsupported package manager: {manager}")

    # ------------------------------------------------------------------
    # VPN / HTTPS helpers
    # ------------------------------------------------------------------
    def _serve_https_enabled(self) -> bool:
        vpn = self.service.metadata.vpn
        return bool(vpn and vpn.serve_https)

    def _webui_port(self) -> int:
        return int(self.service.metadata.runtime.ports.webui)

    def _ensure_https_serving(self) -> None:
        if not self._serve_https_enabled():
            return
        port = self._webui_port()
        try:
            if not self.vpn.is_connected():
                self.vpn.connect()
            self.vpn.serve_https(port)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to serve HTTPS on port {port} via VPN: {exc}"
            ) from exc

    def _ensure_https_stopped(self) -> None:
        if not self._serve_https_enabled():
            return
        port = self._webui_port()
        try:
            self.vpn.stop_serving_https(port)
        except Exception:
            # Stopping the service must not fail because the VPN endpoint was
            # not being served or the VPN is unreachable.
            pass

    def _wait_for_webui(self) -> bool:
        """Wait until the WebUI port accepts connections (best effort)."""
        return self._wait_for_port(self._webui_port(), self.restart_delay)

    def _wait_for_port(self, port: int, timeout: float | None = None) -> bool:
        timeout = self.restart_delay if timeout is None else timeout
        deadline = time.monotonic() + max(float(timeout), 0.0)
        while time.monotonic() < deadline:
            if self._port_is_open(port):
                return True
            time.sleep(0.5)
        return False

    @staticmethod
    def _port_is_open(port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                return sock.connect_ex(("127.0.0.1", int(port))) == 0
        except OSError:
            return False

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------
    def get_groups(self):
        """Get the groups associated with this service."""
        return self.service.metadata.groups

    def get_dependencies(self):
        """Get the dependencies of this service."""
        return self.service.metadata.depends_on

    def get_id(self):
        """Get the unique identifier of this service."""
        return self.service.metadata.id

    def is_active(self):
        """Check if the service is active."""
        return self.service.metadata.active
