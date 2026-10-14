import json
from pathlib import Path

import pytest


def _payload(**overrides) -> str:
    base = {
        "name": "Sonarr",
        "description": "TV series updated",
        "schema_version": 2,
        "id": "sonarr",
        "active": True,
        "runtime": {
            "type": "local",
            "ports": {"webui": 8989},
            "sys_user": "sonarr",
            "sys_group": "media",
        },
        "local": {"installation_path": "/opt/Sonarr", "systemd_services": ["sonarr"]},
        "my_custom_key": {"kept": 42},
    }
    base.update(overrides)
    return json.dumps(base)


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------
def test_show_json(project, run):
    result = run(project["config"], ["metadata", "show", "sonarr", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["id"] == "sonarr"
    assert payload["path"] == str(project["metadata_path"])
    assert payload["service_dir"] == str(project["service_dir"])
    # Raw content preserves unknown keys.
    assert payload["metadata"]["my_custom_key"] == {"nested": True}


def test_show_missing_service(project, run):
    result = run(project["config"], ["metadata", "show", "nope", "--json"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_show_table(project, run):
    result = run(project["config"], ["metadata", "show", "sonarr"])
    assert result.exit_code == 0, result.output
    assert "Sonarr" in result.output


# ---------------------------------------------------------------------------
# set
# ---------------------------------------------------------------------------
def test_set_ok_preserves_unknown_keys_and_backs_up(project, run):
    original = project["metadata_path"].read_text(encoding="utf-8")
    result = run(project["config"], ["metadata", "set", "sonarr", "--json"], input=_payload())
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["path"] == str(project["metadata_path"])

    saved = json.loads(project["metadata_path"].read_text(encoding="utf-8"))
    assert saved["description"] == "TV series updated"
    assert saved["my_custom_key"] == {"kept": 42}

    backup = project["metadata_path"].with_name("sd_info.json.bak")
    assert backup.is_file()
    assert backup.read_text(encoding="utf-8") == original

    warnings = " ".join(payload["warnings"])
    assert "my_custom_key" in warnings


def test_set_validation_failure_does_not_write(project, run):
    original = project["metadata_path"].read_text(encoding="utf-8")
    result = run(
        project["config"],
        ["metadata", "set", "sonarr", "--json"],
        input=_payload(name=""),
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert payload["errors"]
    assert project["metadata_path"].read_text(encoding="utf-8") == original
    assert not project["metadata_path"].with_name("sd_info.json.bak").exists()


def test_set_id_mismatch(project, run):
    result = run(
        project["config"],
        ["metadata", "set", "sonarr", "--json"],
        input=_payload(id="radarr"),
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert any("does not match" in error for error in payload["errors"])


def test_set_allow_id_change(project, run):
    result = run(
        project["config"],
        ["metadata", "set", "sonarr", "--json", "--allow-id-change"],
        input=_payload(id="radarr"),
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert any("id changed" in warning for warning in payload["warnings"])
    saved = json.loads(project["metadata_path"].read_text(encoding="utf-8"))
    assert saved["id"] == "radarr"


def test_set_dry_run(project, run):
    original = project["metadata_path"].read_text(encoding="utf-8")
    result = run(
        project["config"],
        ["metadata", "set", "sonarr", "--json", "--dry-run"],
        input=_payload(),
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert project["metadata_path"].read_text(encoding="utf-8") == original
    assert not project["metadata_path"].with_name("sd_info.json.bak").exists()


def test_set_invalid_json(project, run):
    result = run(project["config"], ["metadata", "set", "sonarr", "--json"], input="{not json")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert "Invalid JSON" in payload["errors"][0]


def test_set_from_file(project, run, tmp_path):
    source = project["root"] / "payload.json"
    source.write_text(_payload(description="From file"), encoding="utf-8")
    result = run(project["config"], ["metadata", "set", "sonarr", "--json", "--file", str(source)])
    assert result.exit_code == 0, result.output
    saved = json.loads(project["metadata_path"].read_text(encoding="utf-8"))
    assert saved["description"] == "From file"


def test_set_missing_service_reports_json(project, run):
    result = run(project["config"], ["metadata", "set", "nope", "--json"], input=_payload())
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert any("not found" in error.lower() for error in payload["errors"])


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------
def test_schema_json(run):
    result = run(None, ["metadata", "schema", "--json"])
    assert result.exit_code == 0, result.output
    schema = json.loads(result.output)
    assert schema["enums"]["runtime_type"] == ["docker", "local", "php"]
    assert "start" in schema["scripts"]["actions"]
    assert "check_update" in schema["enums"]["script_action"]
    assert "docker" in schema["runtime_requirements"]
    paths = {field["path"] for field in schema["fields"]}
    assert {"name", "runtime.type", "scripts.start", "version.latest.strategy"} <= paths
