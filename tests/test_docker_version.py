import json
import re

import pytest

import smanager.service_managers.base_sdv2_manager as bsm
from smanager.datatypes import Service, ServiceMetadata
from smanager.service_managers.docker_manager import DockerManager


def make_manager(tmp_path, compose_file="compose.yaml"):
    service_dir = tmp_path / "svc"
    service_dir.mkdir()
    (service_dir / compose_file).write_text("services: {}\n", encoding="utf-8")
    metadata = ServiceMetadata.from_dict(
        {
            "name": "App",
            "description": "x",
            "schema_version": 2,
            "id": "app",
            "active": True,
            "runtime": {
                "type": "docker",
                "ports": {"webui": 1234},
                "sys_user": "u",
                "sys_group": "g",
            },
            "docker": {"compose_file": compose_file},
            "version": {"latest": {"strategy": "docker"}},
        }
    )
    service = Service(
        metadata=metadata,
        service_abspath=str(service_dir),
        metadata_filename="sd_info.json",
    )
    return DockerManager(service, vpn=None)


def patch(manager, monkeypatch, *, image="myapp:1.2.3", labels=None,
          local_digest="sha256:local", remote_digest="sha256:remote",
          remote_label=None, tools=("docker", "regctl")):
    labels = labels or {}

    def fake_which(name):
        return f"/usr/bin/{name}" if name in tools else None

    monkeypatch.setattr(bsm.shutil, "which", fake_which)

    def fake_cmd(args, timeout=None):
        joined = " ".join(args)
        if args[0] == "docker" and "Config.Labels" in joined:
            match = re.search(r'\.Config\.Labels "([^"]+)"', joined)
            label_name = match.group(1) if match else ""
            return labels.get(label_name, "")
        if args[0] == "docker" and "RepoDigests" in joined:
            return json.dumps([f"myapp@{local_digest}"]) if local_digest else ""
        if args[0] == "docker" and "buildx" in joined:
            return remote_digest or ""
        if args[0] in ("regctl", "crane") and "config" in joined:
            if remote_label is None:
                return ""
            return json.dumps({"config": {"Labels": {"org.opencontainers.image.version": remote_label}}})
        if args[0] == "skopeo":
            if remote_label is None:
                return ""
            return json.dumps({"Labels": {"org.opencontainers.image.version": remote_label}})
        return None

    monkeypatch.setattr(manager, "_cmd_stdout", fake_cmd)
    monkeypatch.setattr(manager, "_docker_compose_images", lambda compose_path: [image])


def test_docker_oci_label_preferred(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    patch(
        manager,
        monkeypatch,
        labels={"org.opencontainers.image.version": "1.2.3"},
        local_digest="sha256:local",
        remote_digest="sha256:remote",
        remote_label="1.4.0",
    )
    info = manager.check_update()
    assert info.current == "1.2.3"
    assert info.current_kind == "version"
    assert info.latest == "1.4.0"
    assert info.latest_kind == "version"
    assert info.current_digest == "sha256:local"
    assert info.latest_digest == "sha256:remote"
    assert info.available is True


def test_docker_version_tag_used_when_no_label(tmp_path, monkeypatch):
    manager = make_manager(tmp_path, )
    patch(manager, monkeypatch, image="myapp:v2.0.1", labels={}, local_digest="sha256:l",
          remote_digest="sha256:r", remote_label=None, tools=("docker",))
    info = manager.check_update()
    assert info.current == "v2.0.1"
    assert info.current_kind == "tag"
    assert info.latest == "sha256:r"
    assert info.latest_kind == "digest"
    assert info.available is True


def test_docker_floating_tag_falls_back_to_digest(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    patch(manager, monkeypatch, image="myapp:latest", labels={}, local_digest="sha256:local",
          remote_digest="sha256:remote", remote_label=None, tools=("docker",))
    info = manager.check_update()
    assert info.current == "sha256:local"
    assert info.current_kind == "digest"


def test_docker_no_tag_falls_back_to_digest(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    patch(manager, monkeypatch, image="myapp", labels={}, local_digest="sha256:local",
          remote_digest="sha256:remote", remote_label=None, tools=("docker",))
    info = manager.check_update()
    assert info.current == "sha256:local"
    assert info.current_kind == "digest"


def test_docker_digest_pinned_ref_never_uses_tag(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    patch(manager, monkeypatch, image="myapp@sha256:deadbeef", labels={}, local_digest="sha256:local",
          remote_digest="sha256:remote", remote_label=None, tools=("docker",))
    info = manager.check_update()
    assert info.current == "sha256:local"
    assert info.current_kind == "digest"


def test_docker_available_false_when_digests_equal(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    patch(manager, monkeypatch, labels={"org.opencontainers.image.version": "1.0.0"},
          local_digest="sha256:same", remote_digest="sha256:same")
    info = manager.check_update()
    assert info.available is False


def test_docker_unknown_when_local_digest_missing(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    patch(manager, monkeypatch, labels={}, local_digest=None, remote_digest="sha256:remote",
          remote_label=None, tools=("docker",))
    info = manager.check_update()
    assert info.available is None
    assert info.latest_digest == "sha256:remote"


def test_docker_remote_label_via_skopeo(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    patch(manager, monkeypatch, labels={}, local_digest="sha256:local", remote_digest="sha256:remote",
          remote_label="3.0.0", tools=("docker", "skopeo"))
    info = manager.check_update()
    assert info.latest == "3.0.0"
    assert info.latest_kind == "version"


def test_docker_no_tools_no_error(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    patch(manager, monkeypatch, labels={}, local_digest="sha256:local", remote_digest=None,
          remote_label=None, tools=())
    info = manager.check_update()
    assert info.error is None
    assert info.latest is None
    assert info.available is None


def test_image_tag_and_version_helpers():
    assert DockerManager._image_tag("ghcr.io/org/app:1.2.3") == "1.2.3"
    assert DockerManager._image_tag("app") is None
    assert DockerManager._image_tag("app@sha256:deadbeef") is None
    assert DockerManager._image_tag("registry:5000/app:v1") == "v1"
    assert DockerManager._looks_like_version("v1.2") is True
    assert DockerManager._looks_like_version("1.2.3") is True
    assert DockerManager._looks_like_version("2024.1") is True
    assert DockerManager._looks_like_version("latest") is False
    assert DockerManager._is_floating_tag("LATEST") is True
    assert DockerManager._is_floating_tag("1.2.3") is False
