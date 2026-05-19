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

@dataclass
class LocalSection:
    installation_path: Optional[str] = None
    app_path: Optional[str] = None
    systemd_services: Optional[list] = None

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
        
        # Validate at least one of docker or local is provided
        if not self.docker and not self.local:
            raise ValueError("SDConfig must have at least one of 'docker' or 'local' sections.")
        
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
        docker = DockerSection(**docker_data) if docker_data else None

        local_data = data.get('local')
        local = LocalSection(**local_data) if local_data else None

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