import click
from pathlib import Path

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
def init_cmd(output: Path | None) -> None:
    """Create a service metadata file using an interactive guided wizard."""
    wizard = MetadataWizard(output_override=output)
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
def edit_cmd(metadata_file: Path | None) -> None:
    """Edit an existing service metadata file interactively."""
    editor = MetadataEditor(metadata_path=metadata_file)
    editor.run()
