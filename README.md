# SManager
> A simple server manager for self-hosted services, with VPN integration and support for both local and Docker-based services.

When building a self-hosted setup, it’s common to end up with dozens of local services, Docker containers, and maintenance scripts scattered across your system. Tasks as simple as restarting or stopping a service can quickly become frustrating when there’s no clear overview of what is running, how components relate to each other, or how everything is managed.

SManager provides a simple and unified CLI for managing both local and Docker services, with built-in support for VPN integration and interactive metadata management.

Reseting all your music-related services becomes as simple as:

```bash
smanager group restart music
```

## Features
- Unified service management for local/systemd and Docker runtimes.
- VPN integration (Tailscale provider support).
- Interactive metadata creation and editing.
- YAML-based global configuration.
- Rich service status reporting with optional JSON output.

# Phylosophy
SManager is designed to work alongside your existing setup, not replace it. However here are some best practices to get the most out of SManager:
- Use one directory per service (service directory), put all the service-related files there (metadata, scripts, Dockerfiles, documentation, etc).
- Define one directory to store all the service directories (services root).
- Each time you create a new service, create a metadata file for it using `smanager metadata init` and place it in its service directory.

SManager does not enforce any specific structure for your services, but following these guidelines will help you maintain a clear and organized setup that SManager can effectively manage. If you don't want to follow this structure, just point `services_root` to your $HOME and SManager will work with whatever it finds there.

# Installation
```bash
pip install smanager
```
After installation, you need to configure SManager by running:

```bash
smanager config init
smanager config edit
```
An editor will open with the global configuration file. Set the `services_root` to the directory where you want to store your service directories, and configure the VPN provider if you are using one.

## CLI Usage
Use this command pattern:

```bash
smanager <group> <command> [options]
```

Discover available commands at any level:

```bash
smanager --help
smanager <group> --help
smanager <group> <command> --help
```

### Status Commands

Status is now a subcommand under each resource group:

```bash
smanager service status <service_id>
smanager group status <group_name>
smanager dependency status <dependency_name>
smanager all status
```

Optional JSON output is available for each status command:

```bash
smanager service status <service_id> --json
```

### Info Commands

Info is available under each resource group and shows service name plus WebUI URL:

```bash
smanager service info <service_id>
smanager group info <group_name>
smanager dependency info <dependency_name>
smanager all info
```

Use `--details` to include extra operational columns:

```bash
smanager service info <service_id> --details
```

## Metadata Commands
The `metadata` group provides interactive workflows for service metadata files.

### Create Metadata
```bash
smanager metadata init
```

Optional output override:

```bash
smanager metadata init --output /path/to/sd_info.json
```

### Edit Existing Metadata
```bash
smanager metadata edit
```

Edit a specific file directly:

```bash
smanager metadata edit --file /path/to/sd_info.json
```

Behavior summary:
- Interactive prompts with inline defaults.
- Runtime-aware sections (Docker vs Local).
- Multi-select support for `groups` and `depends_on`.
- Validation before writing changes.

## Notes
- `metadata init` creates a new file.
- `metadata edit` modifies an existing file.
- Use command-specific `--help` for the latest options and examples.

