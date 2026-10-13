import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ..config import get_manager, get_metadata_filename
from ...datatypes import ServiceMetadata
from ...metadata_ops import (
    KNOWN_TOP_LEVEL_KEYS,
    atomic_write_json,
    build_schema,
    parse_json_text,
    read_json_file,
    render_review,
    render_schema_table,
    validate_metadata_dict,
)


@click.group("metadata")
@click.pass_context
def metadata_cmd(ctx: click.Context) -> None:
    """Create, inspect and manage service metadata files."""
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
    from ..metadata_wizard import MetadataWizard

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
    from ..metadata_wizard import MetadataEditor

    editor = MetadataEditor(metadata_path=metadata_file, metadata_filename=get_metadata_filename(ctx))
    editor.run()


@metadata_cmd.command("show")
@click.argument("service_id")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
@click.pass_context
def show_cmd(ctx: click.Context, service_id: str, as_json: bool) -> None:
    """Show the metadata of a single service."""
    manager = get_manager(ctx)
    try:
        service = manager.get_service(service_id)
    except ValueError as e:
        raise click.ClickException(str(e))

    metadata_path = Path(service.service_abspath) / service.metadata_filename

    if as_json:
        try:
            raw = read_json_file(metadata_path)
        except ValueError as e:
            raise click.ClickException(str(e))
        click.echo(
            json.dumps(
                {
                    "id": service.metadata.id,
                    "path": str(metadata_path),
                    "service_dir": str(service.service_abspath),
                    "metadata": raw,
                },
                indent=2,
            )
        )
        return

    render_review(service.metadata, service.service_abspath, service.metadata_filename)


def _emit_set_result(payload: dict, as_json: bool, *, success: bool) -> None:
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return
    if success:
        click.echo(payload.get("path", "Metadata written."))
        for warning in payload.get("warnings", []):
            click.echo(f"Warning: {warning}", err=True)
    else:
        for error in payload.get("errors", []):
            click.echo(f"Error: {error}", err=True)


@metadata_cmd.command("set")
@click.argument("service_id")
@click.option(
    "--file",
    "input_file",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=None,
    metavar="PATH",
    help="Read the metadata JSON from PATH instead of STDIN.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Validate and report without writing.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
@click.option(
    "--allow-id-change",
    is_flag=True,
    default=False,
    help="Allow the incoming metadata id to differ from SERVICE_ID.",
)
@click.pass_context
def set_cmd(
    ctx: click.Context,
    service_id: str,
    input_file: Path | None,
    dry_run: bool,
    as_json: bool,
    allow_id_change: bool,
) -> None:
    """Replace the metadata of a service from a JSON payload (--file or STDIN)."""

    def fail(errors: list[str]) -> None:
        _emit_set_result({"success": False, "errors": errors}, as_json, success=False)
        ctx.exit(1)

    try:
        if input_file is not None:
            raw = read_json_file(input_file)
        else:
            raw = parse_json_text(click.get_text_stream("stdin").read())
    except ValueError as e:
        fail([str(e)])
        return

    try:
        manager = get_manager(ctx)
        service = manager.get_service(service_id)
    except (click.ClickException, ValueError) as e:
        fail([str(e)])
        return

    metadata_path = Path(service.service_abspath) / service.metadata_filename

    metadata, errors = validate_metadata_dict(raw, metadata_path)
    if errors:
        fail(errors)
        return

    if not allow_id_change and metadata.id != service_id:
        fail(
            [
                f"Metadata id '{metadata.id}' does not match service '{service_id}'. "
                "Use --allow-id-change to override."
            ]
        )
        return

    warnings: list[str] = []
    unknown = sorted(set(raw.keys()) - KNOWN_TOP_LEVEL_KEYS)
    if unknown:
        warnings.append(f"preserved unknown top-level keys: {', '.join(unknown)}")
    if allow_id_change and metadata.id != service_id:
        warnings.append(f"service id changed from '{service_id}' to '{metadata.id}'")

    if dry_run:
        _emit_set_result(
            {
                "success": True,
                "path": str(metadata_path),
                "warnings": warnings,
                "dry_run": True,
            },
            as_json,
            success=True,
        )
        return

    try:
        atomic_write_json(metadata_path, raw, backup=True)
    except OSError as e:
        fail([f"Failed to write metadata: {e}"])
        return

    _emit_set_result(
        {
            "success": True,
            "path": str(metadata_path),
            "warnings": warnings,
            "dry_run": False,
        },
        as_json,
        success=True,
    )


@metadata_cmd.command("schema")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
def schema_cmd(as_json: bool) -> None:
    """Describe the metadata schema (machine readable with --json)."""
    schema = build_schema()
    if as_json:
        click.echo(json.dumps(schema, indent=2))
    else:
        render_schema_table(schema)


def _discover_metadata_files(root: Path, metadata_filename: str) -> list[Path]:
    return sorted(path for path in root.rglob(metadata_filename) if path.is_file())


def _validate_metadata_file(path: Path) -> dict:
    errors: list[str] = []
    metadata: ServiceMetadata | None = None

    try:
        raw_data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
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

    metadata, errors = validate_metadata_dict(raw_data, path)

    runtime_type = metadata.runtime.type if metadata else str(raw_data.get("runtime", {}).get("type", "unknown"))

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
        click.echo(json.dumps(results, indent=2))
    else:
        _render_validation_table(results)

    if invalid_found:
        ctx.exit(1)
