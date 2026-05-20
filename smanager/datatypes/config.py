import yaml
from dataclasses import dataclass, field

@dataclass
class GlobalConfig:
    services_dir: str
    vpn_provider: str = field(default="tailscale")
    metadata_filename: str = field(default="sd_info.json")

    @classmethod
    def from_yaml(cls, yaml_str: str) -> 'GlobalConfig':
        """Parses a YAML string into a GlobalConfig object."""
        try:
            data = yaml.safe_load(yaml_str)
            global_data = data.get('global', {})
            return cls(
                services_dir=global_data.get('services_dir', ''),
                vpn_provider=global_data.get('vpn_provider', 'tailscale'),
                metadata_filename=global_data.get('metadata_filename', 'sd_info.json')
            )
        except yaml.YAMLError as e:
            raise ValueError(f"Error parsing YAML: {e}")