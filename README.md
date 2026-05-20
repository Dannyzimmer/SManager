# SManager
> A simple server manager for self-hosted services, with VPN integration and support for both local and Docker-based services.

## Features
- Unified service management for local/systemd and Docker runtimes.
- VPN integration (Tailscale provider support).
- Interactive metadata creation and editing.
- YAML-based global configuration.

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

