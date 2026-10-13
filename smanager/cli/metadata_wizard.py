"""Interactive wizard for creating service metadata files."""

from __future__ import annotations

import json
import getpass
import os
import re
from pathlib import Path
from typing import Any, Iterable

try:
    import grp
except ImportError:  # pragma: no cover - non-POSIX fallback
    grp = None

import click
from InquirerPy import get_style, inquirer
from InquirerPy.separator import Separator
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..datatypes import ServiceMetadata
from ..metadata_ops import render_review


KNOWN_PORTS = {
    "sonarr": 8989,
    "radarr": 7878,
    "lidarr": 8686,
    "readarr": 8787,
    "prowlarr": 9696,
    "bazarr": 6767,
    "jellyfin": 8096,
    "plex": 32400,
    "qbittorrent": 8080,
    "qbit": 8080,
}

COMPOSE_CANDIDATES = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yml",
    "docker-compose.yaml",
)

ADD_NEW_GROUP_LABEL = "Add new group..."


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "service"


def parse_csv(value: str) -> list[str]:
    if not value.strip():
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def unique_id(base_id: str, existing_ids: Iterable[str]) -> str:
    existing = set(existing_ids)
    candidate = base_id
    suffix = 2
    while candidate in existing:
        candidate = f"{base_id}-{suffix}"
        suffix += 1
    return candidate


def infer_webui_port(service_name: str) -> int:
    normalized = slugify(service_name)
    if normalized in KNOWN_PORTS:
        return KNOWN_PORTS[normalized]
    for key, port in KNOWN_PORTS.items():
        if key in normalized:
            return port
    return 8080


def find_compose_file(service_dir: Path) -> str:
    for candidate in COMPOSE_CANDIDATES:
        if (service_dir / candidate).is_file():
            return candidate
    return "compose.yaml"


def infer_runtime_type(service_dir: Path) -> str:
    for candidate in COMPOSE_CANDIDATES:
        if (service_dir / candidate).is_file():
            return "docker"
    return "local"


def current_system_user() -> str:
    user = getpass.getuser().strip()
    return user or "service"


def current_system_group() -> str:
    if grp is not None and hasattr(os, "getgid"):
        try:
            group_name = grp.getgrgid(os.getgid()).gr_name.strip()
            if group_name:
                return group_name
        except KeyError:
            pass
    return current_system_user()


def discover_existing_metadata(service_root: Path, metadata_filename: str = "sd_info.json") -> tuple[list[str], list[str], list[str]]:
    existing_ids: list[str] = []
    groups: list[str] = []
    dependencies: list[str] = []

    if not service_root.exists():
        return existing_ids, groups, dependencies

    for metadata_path in service_root.rglob(metadata_filename):
        try:
            with metadata_path.open("r", encoding="utf-8") as handle:
                metadata = ServiceMetadata.from_json(handle.read())
        except Exception:
            continue

        existing_ids.append(metadata.id)
        if metadata.groups:
            groups.extend(metadata.groups)
        if metadata.depends_on:
            dependencies.extend(metadata.depends_on)

    return sorted(set(existing_ids)), sorted(set(groups)), sorted(set(dependencies))


class MetadataWizard:
    def __init__(self, output_override: Path | None = None, console: Console | None = None, metadata_filename: str = "sd_info.json"):
        self.output_override = output_override
        self.metadata_filename = metadata_filename
        self.console = console or Console()
        self.prompt_style = get_style(
            {
                "questionmark": "bold white",
                "answermark": "bold green",
                "question": "bold white",
                "answered_question": "bold white",
                "answer": "bold green",
                "instruction": "bold green",
                "long_instruction": "bold green",
                "pointer": "bold green",
                "marker": "bold green",
                "checkbox": "bold green",
            }
        )

    def run(self) -> Path:
        self.console.print(
            Panel.fit(
                "[bold cyan]Service Metadata Wizard[/]\n"
                f"[dim]Create a {self.metadata_filename} file interactively. Press Enter to accept defaults.[/]",
                title="smanager metadata init",
            )
        )

        service_name = self._ask_text("Service name", self._default_service_name())

        base_id = slugify(service_name)
        service_dir = self._resolve_service_dir(self._ask_text("Service directory", self._default_service_dir_display()))

        existing_ids, _, _ = discover_existing_metadata(service_dir.parent, self.metadata_filename)
        service_id = unique_id(base_id, existing_ids)

        metadata_filename = self._default_metadata_filename()
        runtime_type = self._ask_select(
            "Runtime type",
            choices=["docker", "local", "php"],
            default=infer_runtime_type(service_dir),
        )

        description = self._ask_text("Description", f"{service_name} service")
        webui_port = self._ask_int("Web UI port", infer_webui_port(service_name))
        sys_user = self._ask_text("System user", self._default_system_user())
        sys_group = self._ask_text("System group", self._default_system_group())

        docker_section = None
        local_section = None
        php_section = None
        if runtime_type == "docker":
            compose_file = self._ask_text("Compose file", find_compose_file(service_dir))
            containers = parse_csv(self._ask_text("Containers (comma-separated)", ""))
            docker_section = {
                "compose_file": compose_file,
                "containers": containers or None,
            }
        elif runtime_type == "local":
            installation_path = self._ask_text("Installation path", f"/opt/{service_id}")
            appdata_path = self._ask_text("Appdata path", f"/var/lib/{service_id}")
            systemd_services = parse_csv(self._ask_text("Systemd services (comma-separated)", service_id))
            local_section = {
                "installation_path": installation_path,
                "appdata_path": appdata_path,
                "systemd_services": systemd_services or [service_id],
            }
        else:
            start_command = self._ask_text("Start command", f"php-fpm --fpm-config /etc/php-fpm/{service_id}.conf")
            stop_command = self._ask_text("Stop command", "pkill -f php-fpm")
            status_command = self._ask_text("Status command (optional)", "")
            healthcheck_url = self._ask_text("Healthcheck URL", f"http://localhost:{webui_port}/health")
            healthcheck_timeout = self._ask_int("Healthcheck timeout (seconds)", 3)
            working_dir = self._ask_text("Working directory", str(service_dir))
            php_section = {
                "start_command": start_command,
                "stop_command": stop_command,
                "status_command": status_command or None,
                "healthcheck_url": healthcheck_url,
                "healthcheck_timeout": healthcheck_timeout,
                "working_dir": working_dir,
            }

        scripts_section = None
        if self._ask_confirm("Use custom scripts for start/stop/restart", False):
            scripts_section = self._ask_scripts()

        update_section = self._ask_update_section()
        version_section = self._ask_version_section()

        available_groups = self._existing_groups(service_dir)
        available_dependencies = self._existing_dependencies(service_dir, service_id)
        groups = self._ask_groups(available_groups)
        depends_on = self._ask_dependencies(available_dependencies)

        serve_https = self._ask_confirm("Serve HTTPS through VPN", False)
        https_restart_delay = self._ask_int("HTTPS restart delay", 5)
        active = self._ask_confirm("Enable service", True)

        metadata_dict = {
            "name": service_name,
            "description": description,
            "schema_version": 2,
            "id": service_id,
            "active": active,
            "runtime": {
                "type": runtime_type,
                "ports": {"webui": webui_port},
                "sys_user": sys_user,
                "sys_group": sys_group,
            },
            "groups": groups or None,
            "depends_on": depends_on or None,
            "vpn": {
                "serve_https": serve_https,
                "https_restart_delay": https_restart_delay,
            },
        }

        if docker_section is not None:
            metadata_dict["docker"] = docker_section
        if local_section is not None:
            metadata_dict["local"] = local_section
        if php_section is not None:
            metadata_dict["php"] = php_section
        if scripts_section is not None:
            metadata_dict["scripts"] = scripts_section
        if update_section is not None:
            metadata_dict["update"] = update_section
        if version_section is not None:
            metadata_dict["version"] = version_section

        metadata = ServiceMetadata.from_dict(metadata_dict)
        self._render_review(metadata, service_dir, metadata_filename)

        if not self._ask_confirm("Continue", True):
            raise click.ClickException("Cancelled by user.")

        output_path = self._resolve_output_path(service_dir, metadata_filename)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists() and not self._ask_confirm(f"{output_path} already exists. Overwrite", False):
            raise click.ClickException("Cancelled by user.")

        metadata.write_to_json(str(output_path))
        self.console.print(f"[green]✓ Metadata saved to {output_path}[/]")
        return output_path

    def _ask_text(self, label: str, default: str) -> str:
        message = self._inline_prompt_message(label, default)
        return inquirer.text(
            message=message,
            default="",
            mandatory=False,
            transformer=lambda value: value or default,
            filter=lambda value: value or default,
            **self._prompt_config(),
        ).execute()

    def _ask_int(self, label: str, default: int) -> int:
        message = self._inline_prompt_message(label, default)
        value = inquirer.number(
            message=message,
            default=None,
            float_allowed=False,
            replace_mode=True,
            mandatory=False,
            transformer=lambda value: str(default if value == "" else value),
            filter=lambda value: default if value == "" else int(value),
            **self._prompt_config(),
        ).execute()
        return int(value)

    def _ask_confirm(self, label: str, default: bool) -> bool:
        message = self._inline_prompt_message(label, "yes" if default else "no")
        return bool(
            inquirer.confirm(
                message=message,
                default=default,
                transformer=lambda value: "yes" if value else "no",
                instruction="(y/n)",
                **self._prompt_config(),
            ).execute()
        )

    def _ask_scripts(self) -> dict[str, Any] | None:
        section: dict[str, Any] = {}
        for action in ("start", "stop", "restart", "status", "update", "check_update"):
            value = self._ask_text(f"{action.capitalize()} script (.sh path, optional)", "").strip()
            if value:
                section[action] = value
        working_dir = self._ask_text("Scripts working directory (optional)", "").strip()
        if working_dir:
            section["working_dir"] = working_dir
        return section or None

    def _ask_update_section(self) -> dict[str, Any] | None:
        strategy = self._ask_select(
            "Update strategy",
            ["default", "auto", "docker", "git", "composer", "command", "none"],
            "default",
        )
        if strategy == "default":
            return None

        section: dict[str, Any] = {"strategy": strategy}
        if strategy == "command":
            section["command"] = self._ask_text("Update command", "").strip()
        if strategy in {"auto", "git", "composer"}:
            path = self._ask_text("Update path (optional)", "").strip()
            if path:
                section["path"] = path
        if strategy == "git":
            branch = self._ask_text("Git branch (optional)", "").strip()
            if branch:
                section["branch"] = branch
        return section

    def _ask_version_section(self) -> dict[str, Any] | None:
        if not self._ask_confirm("Configure update checks (status --updates)", False):
            return None

        section: dict[str, Any] = {}
        current_command = self._ask_text("Current version command (optional)", "").strip()
        if current_command:
            section["current_command"] = current_command
        regex = self._ask_text("Version regex (optional)", "").strip()
        if regex:
            section["regex"] = regex

        strategy = self._ask_select(
            "Latest version strategy",
            ["auto", "docker", "git", "composer", "github", "command", "script", "package", "none"],
            "auto",
        )
        latest: dict[str, Any] = {"strategy": strategy}
        if strategy == "github":
            repo = self._ask_text("GitHub repo (owner/name)", "").strip()
            if repo:
                latest["repo"] = repo
        elif strategy == "command":
            latest["command"] = self._ask_text("Latest version command", "").strip()
        elif strategy in {"git", "composer"}:
            path = self._ask_text("Path (optional)", "").strip()
            if path:
                latest["path"] = path
        elif strategy == "package":
            latest["package_manager"] = self._ask_select(
                "Package manager", ["apt", "dnf", "pacman", "flatpak"], "apt"
            )
            latest["package"] = self._ask_text("Package name", "").strip()
        section["latest"] = latest
        return section

    def _ask_select(
        self,
        label: str,
        choices: list[Any],
        default: str,
        show_default_in_message: bool = True,
    ) -> str:
        values: list[str] = []
        for choice in choices:
            if isinstance(choice, dict):
                values.append(str(choice.get("value", "")))
            else:
                values.append(str(choice))

        default_str = str(default)
        if default_str not in values:
            default = values[0]
        else:
            default = default_str
        message = self._inline_prompt_message(label, default) if show_default_in_message else label
        return inquirer.select(
            message=message,
            choices=choices,
            default=default,
            instruction="[Use arrows to move]",
            **self._prompt_config(),
        ).execute()

    def _ask_checkbox(self, label: str, choices: list[str], default: list[str] | None = None) -> list[str]:
        message = self._inline_prompt_message(label, default)
        return inquirer.checkbox(
            message=message,
            choices=choices,
            default=default or [],
            instruction="[Use arrows to move, space to select]",
            transformer=self._format_checkbox_answer,
            **self._prompt_config(),
        ).execute()

    def _ask_groups(self, available_groups: list[str]) -> list[str]:
        if not available_groups:
            selected = self._ask_checkbox("Groups", [ADD_NEW_GROUP_LABEL])
        else:
            choices = list(dict.fromkeys(available_groups)) + [ADD_NEW_GROUP_LABEL]
            default = available_groups[:2]
            selected = self._ask_checkbox("Groups", choices, default)

        groups = [group for group in selected if group != ADD_NEW_GROUP_LABEL]
        choices = list(dict.fromkeys(available_groups)) + [ADD_NEW_GROUP_LABEL]

        while ADD_NEW_GROUP_LABEL in selected:
            new_group = self._ask_text("New group name", "").strip()
            if not new_group:
                break
            if new_group not in choices:
                choices.insert(len(choices) - 1, new_group)
            if new_group not in groups:
                groups.append(new_group)
            selected = self._ask_checkbox("Groups", choices, groups)
            groups = [group for group in selected if group != ADD_NEW_GROUP_LABEL]

        return self._dedupe(groups)

    def _ask_dependencies(self, available_dependencies: list[str]) -> list[str]:
        if not available_dependencies:
            self.console.print("[dim]No existing services found, leaving dependencies empty.[/]")
            return []
        default = available_dependencies[:3]
        selected = self._ask_checkbox("Depends on", available_dependencies, default)
        return self._dedupe(selected)

    def _existing_groups(self, service_dir: Path) -> list[str]:
        _, groups, _ = discover_existing_metadata(service_dir.parent, self.metadata_filename)
        return groups

    def _existing_dependencies(self, service_dir: Path, current_service_id: str) -> list[str]:
        ids, _, dependencies = discover_existing_metadata(service_dir.parent, self.metadata_filename)
        combined = sorted(set(ids + dependencies) - {current_service_id})
        return combined

    def _default_service_name(self) -> str:
        if self.output_override is not None:
            return slugify(self.output_override.parent.name)
        return slugify(Path.cwd().name)

    def _default_service_dir_display(self) -> str:
        return "."

    def _resolve_service_dir(self, value: str) -> Path:
        if value.strip() == ".":
            return Path.cwd()
        return Path(value).expanduser()

    def _default_metadata_filename(self) -> str:
        if self.output_override is not None:
            return self.output_override.name
        return self.metadata_filename

    def _default_system_user(self) -> str:
        return current_system_user()

    def _default_system_group(self) -> str:
        return current_system_group()

    def _resolve_output_path(self, service_dir: Path, metadata_filename: str) -> Path:
        if self.output_override is not None:
            return self.output_override
        return service_dir / metadata_filename

    def _render_review(self, metadata: ServiceMetadata, service_dir: Path, metadata_filename: str) -> None:
        render_review(metadata, service_dir, metadata_filename, console=self.console)

    def _dedupe(self, values: list[str]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            if value not in deduped:
                deduped.append(value)
        return deduped

    def _inline_prompt_message(self, label: str, default: object | None = None) -> str:
        if default in (None, ""):
            return label
        if isinstance(default, list):
            if not default:
                return label
            default_text = ", ".join(default)
        else:
            default_text = str(default)
        return f"{label} ({default_text})"

    def _prompt_config(self) -> dict[str, Any]:
        return {
            "style": self.prompt_style,
            "qmark": "?",
            "amark": "✓",
            "raise_keyboard_interrupt": True,
        }

    def _format_checkbox_answer(self, values: list[str]) -> str:
        if not values:
            return "none"
        if len(values) <= 3:
            return ", ".join(values)
        return f"{len(values)} selected"


class MetadataEditor(MetadataWizard):
    ACTION_SEPARATOR = Separator(" ")

    def __init__(self, metadata_path: Path | None = None, console: Console | None = None, metadata_filename: str = "sd_info.json"):
        super().__init__(output_override=None, console=console, metadata_filename=metadata_filename)
        self.metadata_path = metadata_path

    def run(self) -> Path:
        target_path = self._resolve_metadata_path()
        metadata_dict = self._load_metadata_dict(target_path)
        ServiceMetadata.from_dict(metadata_dict)
        original_json = json.dumps(metadata_dict, sort_keys=True)

        while True:
            self._render_editor_header(target_path, "Choose sections and save when ready.")
            section_choices = self._editor_section_choices(metadata_dict)
            section_menu_choices = [self.ACTION_SEPARATOR, *section_choices]
            section = self._ask_select(
                "Edit section",
                section_menu_choices,
                section_choices[0],
                show_default_in_message=False,
            )

            if section == "Save and exit":
                break
            if section == "Exit without saving":
                self.console.print("[yellow]No changes written.[/]")
                return target_path
            if section == "Review current changes":
                self._review_current_changes(metadata_dict, target_path)
                continue

            self._edit_section_fields(section, metadata_dict, target_path)

        metadata = ServiceMetadata.from_dict(metadata_dict)
        self._render_review(metadata, target_path.parent, target_path.name)

        if not self._ask_confirm("Save changes", True):
            raise click.ClickException("Cancelled by user.")

        if json.dumps(metadata_dict, sort_keys=True) == original_json:
            self.console.print("[yellow]No changes detected.[/]")
            return target_path

        metadata.write_to_json(str(target_path))
        self.console.print(f"[green]✓ Metadata saved to {target_path}[/]")
        return target_path

    def _editor_section_choices(self, metadata_dict: dict[str, Any]) -> list[str]:
        vpn_label = "VPN" if metadata_dict.get("vpn") is not None else "VPN (missing)"
        return [
            "Identity",
            "Runtime",
            "Runtime details",
            "Scripts",
            "Update",
            "Version",
            "Groups",
            "Depends on",
            vpn_label,
            "Active",
            self.ACTION_SEPARATOR,
            "Review current changes",
            "Save and exit",
            "Exit without saving",
        ]

    def _render_editor_header(self, target_path: Path, subtitle: str) -> None:
        click.clear()
        self.console.print(
            Panel.fit(
                f"[bold cyan]Metadata Editor[/]\n"
                f"[dim]Editing {target_path}. {subtitle}[/]",
                title="smanager metadata edit",
            )
        )

    def _edit_section_fields(self, section: str, metadata_dict: dict[str, Any], target_path: Path) -> None:
        section_key = "VPN" if section.startswith("VPN") else section

        while True:
            self._render_editor_header(target_path, f"Editing section: {section_key}")
            field_choices = self._section_field_choices(section_key, metadata_dict)
            choices = [self.ACTION_SEPARATOR, *field_choices, self.ACTION_SEPARATOR, "Back to main menu"]
            selected = self._ask_select(
                "Edit field",
                choices,
                field_choices[0],
                show_default_in_message=False,
            )

            if selected == "Back to main menu":
                return

            field_key = selected.split(":", 1)[0].strip()
            self._edit_single_field(section_key, field_key, metadata_dict, target_path)

    def _section_field_choices(self, section_key: str, metadata_dict: dict[str, Any]) -> list[str]:
        if section_key == "Identity":
            field_keys = ["name", "description", "id"]
        elif section_key == "Runtime":
            field_keys = ["type", "ports.webui", "sys_user", "sys_group"]
        elif section_key == "Runtime details":
            runtime_type = metadata_dict.get("runtime", {}).get("type", "local")
            if runtime_type == "docker":
                field_keys = ["docker.compose_file", "docker.containers"]
            elif runtime_type == "php":
                field_keys = [
                    "php.start_command",
                    "php.stop_command",
                    "php.status_command",
                    "php.healthcheck_url",
                    "php.healthcheck_timeout",
                    "php.working_dir",
                ]
            else:
                field_keys = ["local.installation_path", "local.appdata_path", "local.systemd_services"]
        elif section_key == "Scripts":
            field_keys = [
                "scripts.start",
                "scripts.stop",
                "scripts.restart",
                "scripts.status",
                "scripts.update",
                "scripts.check_update",
                "scripts.working_dir",
            ]
        elif section_key == "Update":
            field_keys = [
                "update.strategy",
                "update.command",
                "update.path",
                "update.branch",
            ]
        elif section_key == "Version":
            field_keys = [
                "version.current_command",
                "version.regex",
                "version.latest.strategy",
                "version.latest.repo",
                "version.latest.command",
                "version.latest.path",
                "version.latest.package_manager",
                "version.latest.package",
            ]
        elif section_key == "Groups":
            field_keys = ["groups"]
        elif section_key == "Depends on":
            field_keys = ["depends_on"]
        elif section_key == "VPN":
            field_keys = ["serve_https", "https_restart_delay"]
        elif section_key == "Active":
            field_keys = ["active"]
        else:
            field_keys = []

        return [f"{key}: {self._format_field_value(self._get_field_value(section_key, key, metadata_dict))}" for key in field_keys]

    def _format_field_value(self, value: Any) -> str:
        if value is None:
            return "-"
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, list):
            return ", ".join(str(item) for item in value) or "-"
        return str(value)

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        """Return *value* when it is a mapping, otherwise an empty dict."""
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _ensure_mapping(container: dict[str, Any], key: str) -> dict[str, Any]:
        """Return ``container[key]`` as a dict, creating it when missing or null."""
        value = container.get(key)
        if not isinstance(value, dict):
            value = {}
            container[key] = value
        return value

    def _default_webui_port(self, metadata_dict: dict[str, Any]) -> int:
        runtime = self._as_dict(metadata_dict.get("runtime"))
        ports = self._as_dict(runtime.get("ports"))
        return int(ports.get("webui", 8080))

    def _get_field_value(self, section_key: str, field_key: str, metadata_dict: dict[str, Any]) -> Any:
        if section_key == "Identity":
            return metadata_dict.get(field_key)
        if section_key == "Runtime":
            runtime = self._as_dict(metadata_dict.get("runtime"))
            if field_key == "ports.webui":
                return self._as_dict(runtime.get("ports")).get("webui")
            return runtime.get(field_key)
        if section_key == "Runtime details":
            if field_key.startswith("docker."):
                docker = self._as_dict(metadata_dict.get("docker"))
                return docker.get(field_key.split(".", 1)[1])
            if field_key.startswith("php."):
                php = self._as_dict(metadata_dict.get("php"))
                return php.get(field_key.split(".", 1)[1])
            local = self._as_dict(metadata_dict.get("local"))
            return local.get(field_key.split(".", 1)[1])
        if section_key == "Scripts":
            scripts = self._as_dict(metadata_dict.get("scripts"))
            return scripts.get(field_key.split(".", 1)[1])
        if section_key == "Update":
            update = self._as_dict(metadata_dict.get("update"))
            return update.get(field_key.split(".", 1)[1])
        if section_key == "Version":
            version = self._as_dict(metadata_dict.get("version"))
            subfield = field_key.split(".", 1)[1]
            if subfield.startswith("latest."):
                latest = self._as_dict(version.get("latest"))
                return latest.get(subfield.split(".", 1)[1])
            return version.get(subfield)
        if section_key == "Groups":
            return metadata_dict.get("groups")
        if section_key == "Depends on":
            return metadata_dict.get("depends_on")
        if section_key == "VPN":
            vpn = self._as_dict(metadata_dict.get("vpn"))
            return vpn.get(field_key)
        if section_key == "Active":
            return metadata_dict.get("active")
        return None

    def _edit_single_field(self, section_key: str, field_key: str, metadata_dict: dict[str, Any], target_path: Path) -> None:
        if section_key == "Identity":
            label_map = {
                "name": "Service name",
                "description": "Description",
                "id": "Service id",
            }
            metadata_dict[field_key] = self._ask_text(label_map[field_key], str(metadata_dict.get(field_key, "")))
            return

        if section_key == "Runtime":
            runtime = self._ensure_mapping(metadata_dict, "runtime")
            if field_key == "type":
                runtime_type = self._ask_select("Runtime type", ["docker", "local", "php"], str(runtime.get("type", "local")))
                runtime["type"] = runtime_type
                self._sync_runtime_sections(metadata_dict)
                return

            ports = self._ensure_mapping(runtime, "ports")
            if field_key == "ports.webui":
                ports["webui"] = self._ask_int("Web UI port", int(ports.get("webui", 8080)))
                return

            if field_key == "sys_user":
                runtime["sys_user"] = self._ask_text("System user", str(runtime.get("sys_user", self._default_system_user())))
                return

            if field_key == "sys_group":
                runtime["sys_group"] = self._ask_text("System group", str(runtime.get("sys_group", self._default_system_group())))
                return

        if section_key == "Runtime details":
            if field_key.startswith("docker."):
                docker = self._ensure_mapping(metadata_dict, "docker")
                subfield = field_key.split(".", 1)[1]
                if subfield == "compose_file":
                    docker["compose_file"] = self._ask_text("Compose file", str(docker.get("compose_file", "compose.yaml")))
                elif subfield == "containers":
                    containers = docker.get("containers") or []
                    parsed = parse_csv(self._ask_text("Containers (comma-separated)", ", ".join(containers)))
                    docker["containers"] = parsed or None
                return

            if field_key.startswith("php."):
                php = self._ensure_mapping(metadata_dict, "php")
                subfield = field_key.split(".", 1)[1]
                default_port = self._default_webui_port(metadata_dict)
                if subfield == "start_command":
                    php["start_command"] = self._ask_text("Start command", str(php.get("start_command", "php-fpm")))
                elif subfield == "stop_command":
                    php["stop_command"] = self._ask_text("Stop command", str(php.get("stop_command", "pkill -f php-fpm")))
                elif subfield == "status_command":
                    php["status_command"] = self._ask_text(
                        "Status command (optional)",
                        str(php.get("status_command", "")),
                    ) or None
                elif subfield == "healthcheck_url":
                    php["healthcheck_url"] = self._ask_text(
                        "Healthcheck URL",
                        str(php.get("healthcheck_url", f"http://localhost:{default_port}/health")),
                    )
                elif subfield == "healthcheck_timeout":
                    php["healthcheck_timeout"] = self._ask_int(
                        "Healthcheck timeout (seconds)",
                        int(php.get("healthcheck_timeout", 3)),
                    )
                elif subfield == "working_dir":
                    php["working_dir"] = self._ask_text(
                        "Working directory",
                        str(php.get("working_dir", str(target_path.parent))),
                    )
                return

            local = self._ensure_mapping(metadata_dict, "local")
            service_id = str(metadata_dict.get("id", "service"))
            subfield = field_key.split(".", 1)[1]
            if subfield == "installation_path":
                local["installation_path"] = self._ask_text("Installation path", str(local.get("installation_path", f"/opt/{service_id}")))
            elif subfield == "appdata_path":
                local["appdata_path"] = self._ask_text("Appdata path", str(local.get("appdata_path", f"/var/lib/{service_id}")))
            elif subfield == "systemd_services":
                services = local.get("systemd_services") or [service_id]
                parsed = parse_csv(self._ask_text("Systemd services (comma-separated)", ", ".join(services)))
                local["systemd_services"] = parsed or [service_id]
            return

        if section_key == "Scripts":
            scripts = self._ensure_mapping(metadata_dict, "scripts")
            subfield = field_key.split(".", 1)[1]
            if subfield == "working_dir":
                value = self._ask_text(
                    "Scripts working directory",
                    str(scripts.get("working_dir", "")),
                ).strip()
            else:
                value = self._ask_text(
                    f"{subfield.capitalize()} script (.sh path)",
                    str(scripts.get(subfield, "")),
                ).strip()
            if value:
                scripts[subfield] = value
            else:
                scripts.pop(subfield, None)
            if not scripts:
                metadata_dict.pop("scripts", None)
            return

        if section_key == "Update":
            update = self._ensure_mapping(metadata_dict, "update")
            subfield = field_key.split(".", 1)[1]
            if subfield == "strategy":
                update["strategy"] = self._ask_select(
                    "Update strategy",
                    ["auto", "docker", "git", "composer", "command", "none"],
                    str(update.get("strategy", "auto")),
                )
            elif subfield == "command":
                update["command"] = self._ask_text(
                    "Update command", str(update.get("command", ""))
                ) or None
            elif subfield == "path":
                update["path"] = self._ask_text(
                    "Update path", str(update.get("path", ""))
                ) or None
            elif subfield == "branch":
                update["branch"] = self._ask_text(
                    "Git branch", str(update.get("branch", ""))
                ) or None
            return

        if section_key == "Version":
            version = self._ensure_mapping(metadata_dict, "version")
            subfield = field_key.split(".", 1)[1]
            if subfield == "current_command":
                version["current_command"] = self._ask_text(
                    "Current version command", str(version.get("current_command", ""))
                ) or None
            elif subfield == "regex":
                version["regex"] = self._ask_text(
                    "Version regex", str(version.get("regex", ""))
                ) or None
            elif subfield.startswith("latest."):
                latest = self._ensure_mapping(version, "latest")
                key = subfield.split(".", 1)[1]
                if key == "strategy":
                    latest["strategy"] = self._ask_select(
                        "Latest version strategy",
                        ["auto", "docker", "git", "composer", "github", "command", "script", "package", "none"],
                        str(latest.get("strategy", "auto")),
                    )
                elif key == "package_manager":
                    latest["package_manager"] = self._ask_select(
                        "Package manager", ["apt", "dnf", "pacman", "flatpak"],
                        str(latest.get("package_manager", "apt")),
                    )
                else:
                    latest[key] = self._ask_text(
                        key.replace("_", " ").capitalize(), str(latest.get(key, ""))
                    ) or None
            return

        if section_key == "Groups":
            self._edit_groups(metadata_dict, target_path)
            return

        if section_key == "Depends on":
            self._edit_dependencies(metadata_dict, target_path)
            return

        if section_key == "VPN":
            vpn = self._ensure_mapping(metadata_dict, "vpn")
            if field_key == "serve_https":
                vpn["serve_https"] = self._ask_confirm("Serve HTTPS through VPN", bool(vpn.get("serve_https", False)))
            elif field_key == "https_restart_delay":
                vpn["https_restart_delay"] = self._ask_int("HTTPS restart delay", int(vpn.get("https_restart_delay", 5)))
            return

        if section_key == "Active":
            metadata_dict["active"] = self._ask_confirm("Enable service", bool(metadata_dict.get("active", True)))

    def _sync_runtime_sections(self, metadata_dict: dict[str, Any]) -> None:
        runtime = self._ensure_mapping(metadata_dict, "runtime")
        runtime_type = str(runtime.get("type", "local"))

        if runtime_type == "docker":
            metadata_dict.pop("local", None)
            metadata_dict.pop("php", None)
            if not isinstance(metadata_dict.get("docker"), dict):
                metadata_dict["docker"] = {"compose_file": "compose.yaml", "containers": None}
            return

        if runtime_type == "php":
            metadata_dict.pop("docker", None)
            metadata_dict.pop("local", None)
            default_port = self._default_webui_port(metadata_dict)
            if not isinstance(metadata_dict.get("php"), dict):
                metadata_dict["php"] = {
                    "start_command": "php-fpm",
                    "stop_command": "pkill -f php-fpm",
                    "status_command": None,
                    "healthcheck_url": f"http://localhost:{default_port}/health",
                    "healthcheck_timeout": 3,
                    "working_dir": ".",
                }
            return

        metadata_dict.pop("docker", None)
        metadata_dict.pop("php", None)
        service_id = str(metadata_dict.get("id", "service"))
        if not isinstance(metadata_dict.get("local"), dict):
            metadata_dict["local"] = {
                "installation_path": f"/opt/{service_id}",
                "appdata_path": f"/var/lib/{service_id}",
                "systemd_services": [service_id],
            }

    def _review_current_changes(self, metadata_dict: dict[str, Any], target_path: Path) -> None:
        self._render_editor_header(target_path, "Reviewing current changes")
        try:
            metadata = ServiceMetadata.from_dict(metadata_dict)
        except ValueError as exc:
            self.console.print(f"[red]Cannot render review yet: {exc}[/]")
            click.pause("Press Enter to continue...")
            return

        self._render_review(metadata, target_path.parent, target_path.name)
        click.pause("Press Enter to continue...")

    def _resolve_metadata_path(self) -> Path:
        if self.metadata_path is not None:
            target_path = self.metadata_path.expanduser()
        else:
            candidates = self._discover_metadata_files(Path.cwd())
            if not candidates:
                raise click.ClickException(f"No metadata files found (expected {self.metadata_filename}).") 
            if len(candidates) == 1:
                target_path = candidates[0]
            else:
                default_choice = str(candidates[0])
                selected = self._ask_select("Metadata file", [str(path) for path in candidates], default_choice)
                target_path = Path(selected)

        if not target_path.is_file():
            raise click.ClickException(f"Metadata file not found: {target_path}")
        return target_path

    def _discover_metadata_files(self, root: Path) -> list[Path]:
        return sorted(path for path in root.rglob(self.metadata_filename) if path.is_file())

    def _load_metadata_dict(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise click.ClickException(f"Invalid JSON metadata file: {path}") from exc

    def _edit_groups(self, metadata_dict: dict[str, Any], target_path: Path) -> None:
        current = metadata_dict.get("groups") or []
        available = sorted(set(self._existing_groups(target_path.parent) + current))
        metadata_dict["groups"] = self._ask_groups(available) or None

    def _edit_dependencies(self, metadata_dict: dict[str, Any], target_path: Path) -> None:
        service_id = str(metadata_dict.get("id", ""))
        current = metadata_dict.get("depends_on") or []
        available = sorted(set(self._existing_dependencies(target_path.parent, service_id) + current) - {service_id})
        metadata_dict["depends_on"] = self._ask_dependencies(available) or None
