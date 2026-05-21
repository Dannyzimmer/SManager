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

