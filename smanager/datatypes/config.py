import yaml
from dataclasses import dataclass
from abc import classmethod

@dataclass
class GlobalConfig:
    services_dir: str

    @classmethod
    def from_yaml(cls, yaml_str: str) -> 'GlobalConfig':
        """Parses a YAML string into a GlobalConfig object."""
        try:
            data = yaml.safe_load(yaml_str)
            global_data = data.get('global', {})
            return cls(services_dir=global_data.get('services_dir', ''))
        except yaml.YAMLError as e:
            raise ValueError(f"Error parsing YAML: {e}")