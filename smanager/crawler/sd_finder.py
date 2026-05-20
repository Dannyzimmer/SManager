"""
Finds Service Discovery files in a given directory and parses them into Service objects.
"""

import os
from ..datatypes import ServiceMetadata, Service

class ServiceDiscoverer:
    def __init__(self, directory: str, searched_filename: str):
        self.directory = directory
        self.searched_filename = searched_filename

    def discover_services(self) -> list[Service]:
        """Walks through the directory to find SDConfig files, returns a list 
        of Service objects.
        """
        services = []
        for root, _, files in os.walk(self.directory):
            if self.searched_filename in files:
                sd_abspath = os.path.join(root, self.searched_filename)
                with open(sd_abspath, 'r') as f:
                    try:
                        metadata = ServiceMetadata.from_json(f.read())
                        service = Service(
                            metadata=metadata, 
                            service_abspath=root,
                            metadata_filename=self.searched_filename
                            )
                        services.append(service)
                    except Exception as e:
                        raise ValueError(f"Error parsing {sd_abspath}: {e}") from e
        return services
