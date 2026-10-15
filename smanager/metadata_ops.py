"""Non-interactive metadata helpers.

This module deliberately avoids importing InquirerPy or any interactive
dependency so it can be reused from automated, TTY-less contexts (e.g. a web
panel invoking ``smanager metadata show|set|schema --json``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from .datatypes import ServiceMetadata
from .datatypes.sd_info_v2 import (
    ADDITIONAL_REQUIRED_SCRIPTS,
    PACKAGE_MANAGERS,
    SYSTEMD_PRIVILEGES,
    UPDATE_STRATEGIES,
    VERSION_STRATEGIES,
)


KNOWN_TOP_LEVEL_KEYS = {
    "name",
    "description",
    "schema_version",
    "id",
    "active",
    "runtime",
    "groups",
    "docker",
    "local",
    "php",
    "scripts",
    "update",
    "version",
    "vpn",
    "depends_on",
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_php_rules(metadata: ServiceMetadata, metadata_path: Path) -> list[str]:
    errors: list[str] = []
    php = metadata.php
    if php is None:
        errors.append("runtime.type=php requires section 'php'.")
        return errors

    if not str(php.start_command or "").strip():
        errors.append("php.start_command must be a non-empty string.")
    if not str(php.stop_command or "").strip():
        errors.append("php.stop_command must be a non-empty string.")
    if php.status_command is not None and not str(php.status_command).strip():
        errors.append("php.status_command must be a non-empty string when provided.")

    if php.working_dir:
        working_dir_path = Path(php.working_dir)
        if not working_dir_path.is_absolute():
            working_dir_path = metadata_path.parent / working_dir_path
        if not working_dir_path.exists() or not working_dir_path.is_dir():
            errors.append(f"php.working_dir does not exist or is not a directory: {working_dir_path}")

    if php.healthcheck_url:
        parsed = urlparse(php.healthcheck_url)
        if parsed.scheme not in {"http", "https"}:
            errors.append("php.healthcheck_url must use http or https scheme.")
        if not parsed.netloc:
            errors.append("php.healthcheck_url must include a host.")

    return errors


def validate_scripts_rules(metadata: ServiceMetadata, metadata_path: Path) -> list[str]:
    errors: list[str] = []
    scripts = metadata.scripts
    if scripts is None:
        return errors

    for action in ADDITIONAL_REQUIRED_SCRIPTS:
        value = getattr(scripts, action, None)
        if value is None or not str(value).strip():
            continue
        script_path = Path(str(value)).expanduser()
        if not script_path.is_absolute():
            script_path = metadata_path.parent / script_path
        if not script_path.is_file():
            errors.append(f"scripts.{action} file not found: {script_path}")

    if scripts.working_dir:
        working_dir = Path(str(scripts.working_dir)).expanduser()
        if not working_dir.is_absolute():
            working_dir = metadata_path.parent / working_dir
        if not working_dir.is_dir():
            errors.append(
                f"scripts.working_dir does not exist or is not a directory: {working_dir}"
            )

    return errors


def validate_update_rules(metadata: ServiceMetadata, metadata_path: Path) -> list[str]:
    errors: list[str] = []
    update = metadata.update
    if update is None:
        return errors

    if update.strategy == "command" and not str(update.command or "").strip():
        errors.append("update.command must be a non-empty string when strategy is 'command'.")

    if update.args is not None and not isinstance(update.args, list):
        errors.append("update.args must be a list when provided.")

    if update.path:
        update_path = Path(str(update.path)).expanduser()
        if not update_path.is_absolute():
            update_path = metadata_path.parent / update_path
        if not update_path.is_dir():
            errors.append(f"update.path does not exist or is not a directory: {update_path}")
        elif update.strategy == "git" and not (update_path / ".git").is_dir():
            errors.append(f"update.strategy 'git' but no git repository at: {update_path}")
        elif update.strategy == "composer" and not (update_path / "composer.json").is_file():
            errors.append(f"update.strategy 'composer' but no composer.json at: {update_path}")

    return errors


def validate_version_rules(metadata: ServiceMetadata, metadata_path: Path) -> list[str]:
    errors: list[str] = []
    version = metadata.version
    if version is None:
        return errors

    if version.regex is not None:
        try:
            re.compile(version.regex)
        except re.error as exc:
            errors.append(f"version.regex is not valid: {exc}")

    latest = version.latest
    if latest is None:
        return errors

    if latest.strategy == "script" and not (
        metadata.scripts and metadata.scripts.overrides("check_update")
    ):
        errors.append("version.latest.strategy 'script' requires 'scripts.check_update'.")
    if latest.strategy == "github" and latest.repo and "/" not in latest.repo:
        errors.append("version.latest.repo must use the 'owner/name' format.")
    if latest.strategy == "package":
        if latest.package_manager not in PACKAGE_MANAGERS:
            errors.append(
                "version.latest.package_manager must be one of "
                f"{', '.join(PACKAGE_MANAGERS)}."
            )
        if not str(latest.package or "").strip():
            errors.append("version.latest.package is required when strategy is 'package'.")

    if latest.path:
        latest_path = Path(str(latest.path)).expanduser()
        if not latest_path.is_absolute():
            latest_path = metadata_path.parent / latest_path
        if not latest_path.is_dir():
            errors.append(f"version.latest.path does not exist or is not a directory: {latest_path}")

    return errors


def _raw_runtime_type(raw: dict) -> str:
    runtime = raw.get("runtime")
    if isinstance(runtime, dict):
        return str(runtime.get("type", "unknown"))
    return "unknown"


def validate_metadata_dict(
    raw: Any,
    metadata_path: Path,
) -> tuple[Optional[ServiceMetadata], list[str]]:
    """Validate a raw metadata dict with the model plus the extra rules."""
    if not isinstance(raw, dict):
        return None, ["Metadata must be a JSON object."]

    errors: list[str] = []
    metadata: Optional[ServiceMetadata] = None
    try:
        metadata = ServiceMetadata.from_dict(raw)
    except ValueError as exc:
        errors.append(str(exc))

    runtime_type = metadata.runtime.type if metadata else _raw_runtime_type(raw)

    if metadata and runtime_type == "php":
        errors.extend(validate_php_rules(metadata, metadata_path))

    if metadata:
        errors.extend(validate_scripts_rules(metadata, metadata_path))
        errors.extend(validate_update_rules(metadata, metadata_path))
        errors.extend(validate_version_rules(metadata, metadata_path))

    return metadata, errors


# ---------------------------------------------------------------------------
# JSON IO
# ---------------------------------------------------------------------------
def read_json_file(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read file {path}: {exc}") from exc
    return parse_json_text(text)


def parse_json_text(text: str) -> Any:
    if not text or not text.strip():
        raise ValueError("Empty JSON input.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc


def atomic_write_json(path: Path, data: Any, backup: bool = True) -> None:
    """Write *data* as JSON to *path* atomically, keeping a ``.bak`` copy.

    When the target already exists its owner/group and permission bits are
    preserved, so a privileged writer (the daemon running as root) never leaves
    a metadata file owned by root.
    """
    path = Path(path)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    original_stat = None
    try:
        original_stat = path.stat()
    except OSError:
        original_stat = None

    fd, tmp_name = tempfile.mkstemp(dir=str(parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=4)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if original_stat is not None:
            try:
                os.chmod(tmp_name, original_stat.st_mode & 0o7777)
            except OSError:
                pass
            try:
                os.chown(tmp_name, original_stat.st_uid, original_stat.st_gid)
            except OSError:
                pass
        if backup and path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_review(metadata: ServiceMetadata, service_dir, metadata_filename: str, console=None) -> None:
    """Render a human-readable review table for a service metadata object."""
    from rich.console import Console
    from rich.table import Table

    if console is None:
        console = Console()

    table = Table(title="Review", header_style="bold cyan", show_lines=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")

    runtime = metadata.runtime.type
    runtime_details = (
        f"{runtime} ({metadata.runtime.sys_user}/{metadata.runtime.sys_group}, "
        f"port {metadata.runtime.ports.webui})"
    )
    table.add_row("ID", metadata.id)
    table.add_row("Name", metadata.name)
    table.add_row("Description", metadata.description)
    table.add_row("Runtime", runtime_details)
    table.add_row("Service dir", str(service_dir))
    table.add_row("Metadata file", metadata_filename)
    table.add_row("Groups", ", ".join(metadata.groups or []) or "-")
    table.add_row("Depends on", ", ".join(metadata.depends_on or []) or "-")
    if metadata.vpn is not None:
        table.add_row("VPN", f"serve_https={metadata.vpn.serve_https}, delay={metadata.vpn.https_restart_delay}")
    else:
        table.add_row("VPN", "-")

    if metadata.docker is not None:
        table.add_row("Docker compose", metadata.docker.compose_file or "-")
        table.add_row("Containers", ", ".join(metadata.docker.containers or []) or "-")
    if metadata.local is not None:
        table.add_row("Installation path", metadata.local.installation_path or "-")
        table.add_row("Appdata path", metadata.local.appdata_path or "-")
        table.add_row("Systemd services", ", ".join(metadata.local.systemd_services or []) or "-")
        table.add_row("Systemd privilege", metadata.local.privilege or "auto")
    if metadata.php is not None:
        table.add_row("PHP start command", metadata.php.start_command or "-")
        table.add_row("PHP stop command", metadata.php.stop_command or "-")
        table.add_row("PHP status command", metadata.php.status_command or "-")
        table.add_row("Healthcheck", metadata.php.healthcheck_url or "-")
        table.add_row("Healthcheck timeout", str(metadata.php.healthcheck_timeout))
        table.add_row("Working dir", metadata.php.working_dir or "-")

    if metadata.scripts is not None:
        for action in ADDITIONAL_REQUIRED_SCRIPTS:
            table.add_row(f"Script {action}", getattr(metadata.scripts, action) or "-")
        table.add_row("Script working dir", metadata.scripts.working_dir or "-")

    if metadata.update is not None:
        table.add_row("Update strategy", metadata.update.strategy)
        table.add_row("Update command", metadata.update.command or "-")
        table.add_row("Update path", metadata.update.path or "-")
        table.add_row("Update branch", metadata.update.branch or "-")

    if metadata.version is not None:
        table.add_row("Current version command", metadata.version.current_command or "-")
        table.add_row("Version regex", metadata.version.regex or "-")
        if metadata.version.latest is not None:
            table.add_row("Latest version strategy", metadata.version.latest.strategy)
            table.add_row("Latest version repo", metadata.version.latest.repo or "-")
            table.add_row("Latest version command", metadata.version.latest.command or "-")
            table.add_row("Latest version path", metadata.version.latest.path or "-")

    table.add_row("Active", "yes" if metadata.active else "no")
    console.print(table)


# ---------------------------------------------------------------------------
# Schema descriptor
# ---------------------------------------------------------------------------
def _field(path: str, section: str, type_: str, *, required: bool = False,
           enum: str | None = None, default: Any = None, nullable: bool = True,
           description: str = "") -> dict:
    return {
        "path": path,
        "section": section,
        "type": type_,
        "required": required,
        "enum": enum,
        "default": default,
        "nullable": nullable,
        "description": description,
    }


def build_schema() -> dict:
    """Machine-readable descriptor of the metadata schema for UI generation."""
    fields = [
        _field("name", "identity", "string", required=True, nullable=False),
        _field("description", "identity", "string", required=True, nullable=False),
        _field("schema_version", "identity", "integer", required=True, default=2, nullable=False),
        _field("id", "identity", "string", required=True, nullable=False),
        _field("active", "identity", "boolean", default=True, nullable=False),
        _field("runtime.type", "runtime", "enum", required=True, enum="runtime_type", nullable=False),
        _field("runtime.ports.webui", "runtime", "integer", required=True, nullable=False),
        _field("runtime.sys_user", "runtime", "string", required=True, nullable=False),
        _field("runtime.sys_group", "runtime", "string", required=True, nullable=False),
        _field("groups", "organization", "list[string]"),
        _field("depends_on", "organization", "list[string]"),
        _field("docker.compose_file", "docker", "string", description="Required for docker runtime unless scripts.start/stop are set"),
        _field("docker.containers", "docker", "list[string]"),
        _field("local.installation_path", "local", "string"),
        _field("local.appdata_path", "local", "string"),
        _field("local.systemd_services", "local", "list[string]", description="Required for local runtime unless scripts.start/stop are set"),
        _field("local.privilege", "local", "enum", enum="systemd_privilege", default="auto"),
        _field("php.start_command", "php", "string", description="Required for php runtime unless scripts.start is set"),
        _field("php.stop_command", "php", "string", description="Required for php runtime unless scripts.stop is set"),
        _field("php.status_command", "php", "string"),
        _field("php.healthcheck_url", "php", "string"),
        _field("php.healthcheck_timeout", "php", "integer", default=3),
        _field("php.working_dir", "php", "string"),
        _field("php.env", "php", "object"),
    ]

    for action in ADDITIONAL_REQUIRED_SCRIPTS:
        fields.append(_field(f"scripts.{action}", "scripts", "string", description="Path to a shell script"))
    fields.append(_field("scripts.working_dir", "scripts", "string"))
    fields.append(_field("scripts.env", "scripts", "object"))

    fields.extend([
        _field("update.strategy", "update", "enum", enum="update_strategy", default="auto"),
        _field("update.command", "update", "string"),
        _field("update.path", "update", "string"),
        _field("update.branch", "update", "string"),
        _field("update.args", "update", "list[string]"),
        _field("version.current_command", "version", "string"),
        _field("version.regex", "version", "string"),
        _field("version.latest.strategy", "version", "enum", enum="version_strategy", default="auto"),
        _field("version.latest.repo", "version", "string"),
        _field("version.latest.command", "version", "string"),
        _field("version.latest.path", "version", "string"),
        _field("version.latest.branch", "version", "string"),
        _field("version.latest.package_manager", "version", "enum", enum="package_manager"),
        _field("version.latest.package", "version", "string"),
        _field("version.latest.args", "version", "list[string]"),
        _field("vpn.serve_https", "vpn", "boolean", default=False, nullable=False),
        _field("vpn.https_restart_delay", "vpn", "integer", default=5, nullable=False),
    ])

    return {
        "schema_version": 2,
        "enums": {
            "runtime_type": ["docker", "local", "php"],
            "update_strategy": list(UPDATE_STRATEGIES),
            "version_strategy": list(VERSION_STRATEGIES),
            "package_manager": list(PACKAGE_MANAGERS),
            "script_action": list(ADDITIONAL_REQUIRED_SCRIPTS),
            "systemd_privilege": list(SYSTEMD_PRIVILEGES),
        },
        "scripts": {"actions": list(ADDITIONAL_REQUIRED_SCRIPTS)},
        "runtime_requirements": {
            "docker": {
                "required": ["docker.compose_file"],
                "unless": ["scripts.start", "scripts.stop"],
            },
            "local": {
                "required": ["local.systemd_services"],
                "unless": ["scripts.start", "scripts.stop"],
            },
            "php": {
                "required": ["php.start_command", "php.stop_command"],
                "unless": ["scripts.start", "scripts.stop"],
            },
        },
        "fields": fields,
    }


def render_schema_table(schema: dict, console=None) -> None:
    """Render a compact human-readable summary of the schema descriptor."""
    from rich.console import Console
    from rich.table import Table

    if console is None:
        console = Console()

    enums = schema.get("enums", {})
    enum_table = Table(title="Metadata Schema — Enums", header_style="bold cyan", show_lines=False)
    enum_table.add_column("name", style="bold", no_wrap=True)
    enum_table.add_column("values")
    for name, values in enums.items():
        enum_table.add_row(name, ", ".join(str(item) for item in values))
    console.print(enum_table)

    field_table = Table(title="Metadata Schema — Fields", header_style="bold cyan", show_lines=False)
    field_table.add_column("path", style="bold")
    field_table.add_column("type", no_wrap=True)
    field_table.add_column("required", no_wrap=True)
    field_table.add_column("default")
    for field in schema.get("fields", []):
        default = field.get("default")
        field_table.add_row(
            field["path"],
            field.get("enum") or field["type"],
            "yes" if field.get("required") else "no",
            "-" if default is None else str(default),
        )
    console.print(field_table)
