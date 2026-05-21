"""
This module defines the data structures for the SDConfig v2
"""
from dataclasses import dataclass
from typing import Optional
import json
import os


@dataclass
class PortSection:
    webui: int

    # Dinamically loads dict keys as attributes
    def __post_init__(self):
        for key, value in self.__dict__.items():
            setattr(self, key, value)

        if not hasattr(self, 'webui'):
            raise ValueError("PortSection must have a 'webui' key.")

@dataclass
class RuntimeSection:
    type: str
    ports: PortSection
    sys_user: str
    sys_group: str

    def __post_init__(self):
        if not self.type:
            raise ValueError("RuntimeSection must have a 'type' field.")
        if not self.ports:
            raise ValueError("RuntimeSection must have a 'ports' field.")
        if not self.sys_user:
            raise ValueError("RuntimeSection must have a 'sys_user' field.")
        if not self.sys_group:
            raise ValueError("RuntimeSection must have a 'sys_group' field.")

@dataclass
class DockerSection:
    containers: Optional[list] = None
    compose_file: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> 'DockerSection':
        return cls(
            containers=data.get('containers'),
            compose_file=data.get('compose_file')
        )

@dataclass
class LocalSection:
    installation_path: Optional[str] = None
    appdata_path: Optional[str] = None
    systemd_services: Optional[list] = None

    @classmethod
    def from_dict(cls, data: dict) -> 'LocalSection':
        return cls(
            installation_path=data.get('installation_path'),
            appdata_path=data.get('appdata_path'),
            systemd_services=data.get('systemd_services')
        )


@dataclass
class PHPSection:
    start_command: Optional[str] = None
    stop_command: Optional[str] = None
    status_command: Optional[str] = None
    healthcheck_url: Optional[str] = None
    healthcheck_timeout: int = 3
    working_dir: Optional[str] = None
    env: Optional[dict] = None

    @classmethod
    def from_dict(cls, data: dict) -> 'PHPSection':
        return cls(
            start_command=data.get('start_command'),
            stop_command=data.get('stop_command'),
            status_command=data.get('status_command'),
            healthcheck_url=data.get('healthcheck_url'),
            healthcheck_timeout=data.get('healthcheck_timeout', 3),
            working_dir=data.get('working_dir'),
            env=data.get('env')
        )
    
@dataclass
class VPNSection:
    serve_https: bool = False
    https_restart_delay: int = 5

    def __post_init__(self):
        if not isinstance(self.serve_https, bool):
            raise ValueError("VPNSection 'serve_https' field must be a boolean.")
        if not isinstance(self.https_restart_delay, int) or self.https_restart_delay < 0:
            raise ValueError("VPNSection 'https_restart_delay' field must be a non-negative integer.")

@dataclass
class ServiceMetadata:
    name: str
    description: str
    schema_version: int
    id: str
    active: bool
    runtime: RuntimeSection
    groups: Optional[list] = None
    docker: Optional[DockerSection] = None
    local: Optional[LocalSection] = None
    php: Optional[PHPSection] = None
    vpn: Optional[VPNSection] = None
    depends_on: Optional[list] = None

    def __post_init__(self):
        # Validate required fields
        if not self.name:
            raise ValueError("SDConfig must have a 'name' field.")
        if not self.description:
            raise ValueError("SDConfig must have a 'description' field.")
        if not self.schema_version:
            raise ValueError("SDConfig must have a 'schema_version' field.")
        if not self.id:
            raise ValueError("SDConfig must have an 'id' field.")
        if self.active is None:
            raise ValueError("SDConfig must have an 'active' field.")
        if not self.runtime:
            raise ValueError("SDConfig must have a 'runtime' field.")
        
        if self.runtime.type not in {"docker", "local", "php"}:
            raise ValueError(
                f"Unsupported runtime type '{self.runtime.type}'. Expected 'docker', 'local', or 'php'."
            )

        if self.runtime.type == "docker":
            if not self.docker:
                raise ValueError(
                    "SDConfig with runtime.type 'docker' must define a 'docker' section."
                )
            if not self.docker.compose_file:
                raise ValueError(
                    "SDConfig with runtime.type 'docker' must define 'docker.compose_file'."
                )

        if self.runtime.type == "local":
            if not self.local:
                raise ValueError(
                    "SDConfig with runtime.type 'local' must define a 'local' section."
                )
            if not self.local.systemd_services:
                raise ValueError(
                    "SDConfig with runtime.type 'local' must define 'local.systemd_services'."
                )

        if self.runtime.type == "php":
            if not self.php:
                raise ValueError(
                    "SDConfig with runtime.type 'php' must define a 'php' section."
                )
            if not self.php.start_command or not str(self.php.start_command).strip():
                raise ValueError(
                    "SDConfig with runtime.type 'php' must define 'php.start_command'."
                )
            if not self.php.stop_command or not str(self.php.stop_command).strip():
                raise ValueError(
                    "SDConfig with runtime.type 'php' must define 'php.stop_command'."
                )
            if self.php.status_command is not None and not str(self.php.status_command).strip():
                raise ValueError(
                    "SDConfig with runtime.type 'php' must define non-empty 'php.status_command' when provided."
                )
            if not isinstance(self.php.healthcheck_timeout, int) or self.php.healthcheck_timeout <= 0:
                raise ValueError(
                    "SDConfig with runtime.type 'php' must define a positive integer 'php.healthcheck_timeout'."
                )

        # Validate at least one metadata section exists for non-runtime consumers.
        if not self.docker and not self.local and not self.php:
            raise ValueError("SDConfig must have at least one of 'docker', 'local', or 'php' sections.")
        
    @classmethod
    def from_dict(cls, data: dict) -> 'ServiceMetadata':
        runtime_data = data.get('runtime')
        if not runtime_data:
            raise ValueError("SDConfig must have a 'runtime' section.")
        
        runtime = RuntimeSection(
            type=runtime_data.get('type'),
            ports=PortSection(**runtime_data.get('ports', {})),
            sys_user=runtime_data.get('sys_user'),
            sys_group=runtime_data.get('sys_group')
        )

        docker_data = data.get('docker')
        docker = DockerSection.from_dict(docker_data) if docker_data is not None else None

        local_data = data.get('local')
        local = LocalSection.from_dict(local_data) if local_data is not None else None

        php_data = data.get('php')
        php = PHPSection.from_dict(php_data) if php_data is not None else None

        vpn_data = data.get('vpn')
        vpn = VPNSection(**vpn_data) if vpn_data is not None else None

        return cls(
            name=data.get('name'),
            description=data.get('description'),
            schema_version=data.get('schema_version'),
            id=data.get('id'),
            groups=data.get('groups'),
            active=data.get('active'),
            runtime=runtime,
            docker=docker,
            local=local,
            php=php,
            vpn=vpn,
            depends_on=data.get('depends_on')
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> 'ServiceMetadata':
        return cls.from_dict(json.loads(json_str))
    
    def write_to_json(self, file_path: str):
        with open(file_path, 'w') as f:
            json.dump(self.__dict__, f, default=lambda o: o.__dict__, indent=4)

@dataclass
class Service:
    metadata: ServiceMetadata
    service_abspath: str
    metadata_filename: str

    def __post_init__(self):
        if not os.path.isabs(self.service_abspath):
            raise ValueError("Service 'service_abspath' must be an absolute path.")
        if not os.path.exists(self.service_abspath):
            raise ValueError(f"Service 'service_abspath' does not exist: {self.service_abspath}")
        if not self.metadata_filename:
            raise ValueError("Service must have a 'metadata_filename' field.")