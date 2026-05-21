import click
from pathlib import Path

from ..config import get_metadata_filename
from ..metadata_wizard import MetadataEditor, MetadataWizard


@click.group("metadata")
def metadata_cmd() -> None:
    """Create and manage service metadata files interactively."""


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
