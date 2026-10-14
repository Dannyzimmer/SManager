import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from smanager.cli.main import cli


BASE_METADATA = {
    "name": "Sonarr",
    "description": "TV series",
    "schema_version": 2,
    "id": "sonarr",
    "active": True,
    "runtime": {
        "type": "local",
        "ports": {"webui": 8989},
        "sys_user": "sonarr",
        "sys_group": "media",
    },
    "local": {
        "installation_path": "/opt/Sonarr",
        "appdata_path": "/var/lib/sonarr",
        "systemd_services": ["sonarr"],
    },
    "groups": ["media"],
    "my_custom_key": {"nested": True},
    "vpn": {"serve_https": True, "https_restart_delay": 5},
}


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project(tmp_path: Path):
    services_root = tmp_path / "services"
    service_dir = services_root / "sonarr"
    service_dir.mkdir(parents=True)
    metadata_path = service_dir / "sd_info.json"
    metadata_path.write_text(json.dumps(BASE_METADATA, indent=4), encoding="utf-8")

    config_path = tmp_path / "smanager.yaml"
    config_path.write_text(
        "global:\n"
        f'  services_root: "{services_root}"\n'
        '  vpn_provider: "tailscale"\n'
        '  metadata_filename: "sd_info.json"\n',
        encoding="utf-8",
    )

    return {
        "root": tmp_path,
        "config": config_path,
        "services_root": services_root,
        "service_dir": service_dir,
        "metadata_path": metadata_path,
        "base": BASE_METADATA,
    }


@pytest.fixture
def run(runner: CliRunner):
    def _run(config: Path | None, args: list[str], input: str | None = None):
        cli_args = ["--config", str(config), *args] if config is not None else list(args)
        return runner.invoke(cli, cli_args, input=input, catch_exceptions=False)

    return _run
