import json
import os
import shutil
import subprocess

import click
from rich.console import Console
from rich.table import Table

from ...daemon.install import (
    DEFAULT_CONFIG,
    DEFAULT_GROUP,
    DEFAULT_SOCKET,
    Installer,
)


@click.group("daemon")
def daemon_cmd() -> None:
    """Install and manage the privileged SManager daemon (smanagerd).

    \b
    These commands touch the system (systemd units, group, socket) and require
    root. They never run during 'pip install'.
    """


def _emit_report(report, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(report.to_dict(), indent=2))
        return
    console = Console()
    console.print(f"[bold]{report.action}[/] (dry-run={report.dry_run})")
    if report.files:
        console.print("Files:")
        for path in report.files:
            console.print(f"  {path}")
    if report.commands:
        console.print("Commands:")
        for command in report.commands:
            console.print(f"  {' '.join(command)}")
    for note in report.notes:
        console.print(f"[dim]{note}[/]")


def _require_root(dry_run: bool) -> None:
    if dry_run:
        return
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise click.ClickException("this command requires root; re-run with sudo")


@daemon_cmd.command("install")
@click.option("--group", default=DEFAULT_GROUP, help="Socket group (created if missing).")
@click.option("--socket", default=DEFAULT_SOCKET, help="Unix socket path.")
@click.option("--config", "config_path", default=DEFAULT_CONFIG, help="Config file the daemon reads.")
@click.option("--user", default="root", help="User the daemon runs as.")
@click.option("--exec-path", default=None, metavar="PATH",
              help="Path to the smanagerd executable (auto-detected when omitted).")
@click.option("--dry-run", is_flag=True, default=False, help="Print artifacts without changing the system.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
def install_cmd(
    group: str,
    socket: str,
    config_path: str,
    user: str,
    exec_path: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Install the systemd socket + service for smanagerd."""
    _require_root(dry_run)
    try:
        report = Installer(
            group=group,
            socket=socket,
            config=config_path,
            user=user,
            exec_path=exec_path,
            dry_run=dry_run,
        ).install()
    except ValueError as exc:
        raise click.ClickException(str(exc))
    _emit_report(report, as_json)


@daemon_cmd.command("uninstall")
@click.option("--group", default=DEFAULT_GROUP)
@click.option("--socket", default=DEFAULT_SOCKET)
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--json", "as_json", is_flag=True, default=False)
def uninstall_cmd(group: str, socket: str, dry_run: bool, as_json: bool) -> None:
    """Stop and remove the smanagerd systemd units."""
    _require_root(dry_run)
    report = Installer(group=group, socket=socket, dry_run=dry_run).uninstall()
    _emit_report(report, as_json)


@daemon_cmd.command("status")
@click.option("--json", "as_json", is_flag=True, default=False)
def status_cmd(as_json: bool) -> None:
    """Show whether the smanagerd socket is active."""
    info = Installer().status()
    if as_json:
        click.echo(json.dumps(info, indent=2))
    else:
        click.echo(f"{info.get('service')}: {info.get('active')}")


@daemon_cmd.command("logs")
@click.option("-n", "lines", default=100, show_default=True, help="Number of journal lines.")
def logs_cmd(lines: int) -> None:
    """Show recent smanagerd logs via journalctl."""
    journalctl = shutil.which("journalctl")
    if not journalctl:
        raise click.ClickException("journalctl not found")
    try:
        subprocess.run([journalctl, "-u", "smanagerd", "-n", str(lines)], check=False)
    except OSError as exc:
        raise click.ClickException(str(exc))
