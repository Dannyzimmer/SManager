# SManager
> A simple server manager for self-hosted services, with VPN integration and support for both local and Docker-based services.

## Features
- Manage local services and Docker containers with a unified interface.
- Integrate with Tailscale VPN for secure remote access.
- Monitor service status and logs in real-time.
- Easy configuration using YAML files.
- Extensible architecture for adding new service types and VPN providers.

## Interactive Metadata Wizard
- Create a new service metadata file with `smanager metadata init`.
- The wizard is interactive, shows defaults in context, and only asks Docker-specific or local-specific fields depending on the runtime you choose.
- It uses Rich for a guided terminal experience and validates the generated metadata before saving it.

