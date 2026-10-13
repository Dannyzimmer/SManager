import click
from pathlib import Path
import json as json_module
import re
from urllib.parse import urlparse

from rich.console import Console
from rich.table import Table

from ..config import get_metadata_filename
from ..metadata_wizard import MetadataEditor, MetadataWizard
from ...datatypes import ServiceMetadata


@click.group("metadata")
@click.pass_context
def metadata_cmd(ctx: click.Context) -> None:
    """Create and manage service metadata files interactively."""
    ctx.ensure_object(dict)


@metadata_cmd.command("init")
@click.option(
    "--output",
    type=click.Path(path_type=Path, dir_okay=False, writable=True),
    default=None,
    metavar="PATH",
    help="Override the output metadata file path.",
)
@click.pass_context
def init_cmd(ctx: click.Context, output: Path | None) -> None:
    """Create a service metadata file using an interactive guided wizard."""
    wizard = MetadataWizard(output_override=output, metadata_filename=get_metadata_filename(ctx))
    wizard.run()


@metadata_cmd.command("edit")
@click.option(
    "--file",
    "metadata_file",
    type=click.Path(path_type=Path, dir_okay=False, exists=False),
    default=None,
    metavar="PATH",
    help="Path to an existing metadata file. If omitted, choose interactively.",
)
@click.pass_context
def edit_cmd(ctx: click.Context, metadata_file: Path | None) -> None:
    """Edit an existing service metadata file interactively."""
    editor = MetadataEditor(metadata_path=metadata_file, metadata_filename=get_metadata_filename(ctx))
    editor.run()


def _discover_metadata_files(root: Path, metadata_filename: str) -> list[Path]:
    return sorted(path for path in root.rglob(metadata_filename) if path.is_file())


def _validate_php_rules(metadata: ServiceMetadata, metadata_path: Path) -> list[str]:
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


def _validate_scripts_rules(metadata: ServiceMetadata, metadata_path: Path) -> list[str]:
    errors: list[str] = []
    scripts = metadata.scripts
    if scripts is None:
        return errors

    for action in ("start", "stop", "restart", "status", "update"):
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


def _validate_update_rules(metadata: ServiceMetadata, metadata_path: Path) -> list[str]:
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


def _validate_version_rules(metadata: ServiceMetadata, metadata_path: Path) -> list[str]:
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
        if latest.package_manager not in ("apt", "dnf", "pacman", "flatpak"):
            errors.append("version.latest.package_manager must be apt, dnf, pacman or flatpak.")
        if not str(latest.package or "").strip():
            errors.append("version.latest.package is required when strategy is 'package'.")

    if latest.path:
        latest_path = Path(str(latest.path)).expanduser()
        if not latest_path.is_absolute():
            latest_path = metadata_path.parent / latest_path
        if not latest_path.is_dir():
            errors.append(f"version.latest.path does not exist or is not a directory: {latest_path}")

    return errors


def _validate_metadata_file(path: Path) -> dict:
    errors: list[str] = []
    metadata: ServiceMetadata | None = None

    try:
        raw_data = json_module.loads(path.read_text(encoding="utf-8"))
    except json_module.JSONDecodeError as exc:
        errors.append(f"Invalid JSON: {exc}")
        return {
            "path": str(path),
            "valid": False,
            "runtime": "unknown",
            "errors": errors,
        }
    except OSError as exc:
        errors.append(f"Cannot read file: {exc}")
        return {
            "path": str(path),
            "valid": False,
            "runtime": "unknown",
            "errors": errors,
        }

    try:
        metadata = ServiceMetadata.from_dict(raw_data)
    except ValueError as exc:
        errors.append(str(exc))

    runtime_type = metadata.runtime.type if metadata else str(raw_data.get("runtime", {}).get("type", "unknown"))

    if metadata and runtime_type == "php":
        errors.extend(_validate_php_rules(metadata, path))

    if metadata:
        errors.extend(_validate_scripts_rules(metadata, path))
        errors.extend(_validate_update_rules(metadata, path))
        errors.extend(_validate_version_rules(metadata, path))

    return {
        "path": str(path),
        "valid": len(errors) == 0,
        "runtime": runtime_type,
        "errors": errors,
    }


def _render_validation_table(results: list[dict]) -> None:
    console = Console()
    table = Table(title="Metadata Validation", header_style="bold cyan", show_lines=False)
    table.add_column("file", overflow="fold")
    table.add_column("runtime", no_wrap=True)
    table.add_column("valid", no_wrap=True)
    table.add_column("errors", overflow="fold")

    for result in results:
        table.add_row(
            result["path"],
            result["runtime"],
            "yes" if result["valid"] else "no",
            " | ".join(result["errors"]) if result["errors"] else "-",
        )

    console.print(table)


@metadata_cmd.command("validate")
@click.option(
    "--file",
    "metadata_file",
    type=click.Path(path_type=Path, dir_okay=False, exists=False),
    default=None,
    metavar="PATH",
    help="Validate a single metadata file.",
)
@click.option(
    "--root",
    type=click.Path(path_type=Path, file_okay=False, exists=False),
    default=None,
    metavar="DIR",
    help="Directory to scan recursively when --file is not provided (defaults to current directory).",
)
@click.option("--json", "as_json", is_flag=True, help="Output validation results as JSON.")
@click.pass_context
def validate_cmd(
    ctx: click.Context,
    metadata_file: Path | None,
    root: Path | None,
    as_json: bool,
) -> None:
    """Validate metadata files against schema and runtime-specific rules."""
    metadata_filename = get_metadata_filename(ctx)

    if metadata_file is not None:
        candidates = [metadata_file.expanduser()]
    else:
        scan_root = root.expanduser() if root is not None else Path.cwd()
        candidates = _discover_metadata_files(scan_root, metadata_filename)

    if not candidates:
        raise click.ClickException(f"No metadata files found (expected {metadata_filename}).")

    results = [_validate_metadata_file(path) for path in candidates]
    invalid_found = any(not item["valid"] for item in results)

    if as_json:
        click.echo(json_module.dumps(results, indent=2))
    else:
        _render_validation_table(results)

    if invalid_found:
        ctx.exit(1)
