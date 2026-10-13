# SManager
> A simple server manager for self-hosted services, with VPN integration and support for local/systemd, Docker, and PHP runtimes.

When building a self-hosted setup, it’s common to end up with dozens of local services, Docker containers, and maintenance scripts scattered across your system. Tasks as simple as restarting or stopping a service can quickly become frustrating when there’s no clear overview of what is running, how components relate to each other, or how everything is managed.

SManager provides a simple and unified CLI for managing local, Docker, and PHP services, with built-in support for VPN integration and interactive metadata management.

Reseting all your music-related services becomes as simple as:

```bash
smanager group restart music
```

## Features
- Unified service management for local/systemd, Docker, and PHP runtimes.
- Per-service custom start/stop/restart/status/update scripts.
- One-command updates (Docker Compose out of the box, opt-in git/composer heuristics).
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

### Validate Metadata
Validate a single metadata file:

```bash
smanager metadata validate --file /path/to/sd_info.json
```

Validate all metadata files from a directory recursively:

```bash
smanager metadata validate --root /path/to/services
```

Use JSON output for CI/automation:

```bash
smanager metadata validate --root /path/to/services --json
```

Behavior summary:
- Interactive prompts with inline defaults.
- Runtime-aware sections (Docker, Local, and PHP).
- Multi-select support for `groups` and `depends_on`.
- Validation before writing changes.

### PHP Runtime Metadata
For `runtime.type: php`, define the `php` section with:

- `start_command` (required)
- `stop_command` (required)
- `status_command` (optional, if present takes precedence over healthcheck for `status`)
- `healthcheck_url` (optional, used by status checks)
- `healthcheck_timeout` (optional, defaults to 3)
- `working_dir` (optional)
- `env` (optional map of environment variables)

## Custom Scripts
Any service can override `start`, `stop`, `restart`, `status`, and/or `update`
with a shell script. Provide any subset of them; the operations you do not
override keep using the default mechanism for the runtime type.

```json
{
  "scripts": {
    "start": "scripts/start.sh",
    "stop": "scripts/stop.sh",
    "restart": "scripts/restart.sh",
    "status": "scripts/status.sh",
    "update": "scripts/update.sh",
    "working_dir": ".",
    "env": { "APP_ENV": "production" }
  }
}
```

- Values are paths to `.sh` files, relative to the service directory (or absolute).
- Scripts run with `bash` (fallback `sh`) from `working_dir` (default: the service
  directory), with `env` merged over the current environment.
- `status` exit code drives the result: `0` = running, anything else = stopped.
- A `restart` script owns the stop/start sequence; SManager still re-establishes
  the VPN HTTPS serve afterwards when `vpn.serve_https` is enabled.
- When `scripts.start` and `scripts.stop` are both present, `local.systemd_services`
  and `docker.compose_file` become optional.

## Updating services
Update a single service, a group, a dependency, or everything:

```bash
smanager service update sonarr
smanager group update media
smanager dependency update qbittorrent
smanager all update --yes
```

Add `--dry-run` to print exactly what would run without executing anything
(`smanager all update --dry-run` does not require `--yes`).

Resolution order for `update`:

1. **`scripts.update`** if defined — the script owns the whole update/restart.
2. Otherwise, the **`update`** metadata section:
   - `docker` (default for Docker services): `docker compose pull --ignore-pull-failures`
     followed by `docker compose up -d --build`.
   - `git`: `git -C <path> pull [origin <branch>]`, then an automatic restart.
   - `composer`: `composer --working-dir <path> update --no-interaction`, then a restart.
   - `command`: an inline command (`shlex`-split), which owns the update.
   - `none`: disables updates explicitly.

```json
{
  "update": {
    "strategy": "auto",
    "path": "/opt/sonarr",
    "branch": "main",
    "command": "composer update --no-interaction"
  }
}
```

With `strategy: "auto"` (opt-in), local/PHP services are inspected for a `.git`
directory or a `composer.json`, and the matching strategy is used. Local and PHP
services without `scripts.update` or an `update` section error out clearly.

Inactive services (`active: false`) are skipped by `update`, just like `start`.

## HTTPS over VPN without passwords
By default SManager runs the privileged Tailscale operations **non-interactively**
and never blocks waiting for a password:

1. It first tries the command as the current user (Tailscale *operator* mode).
2. It falls back to `sudo -n` (non-interactive; requires NOPASSWD).

To avoid `sudo` entirely, once per machine run:

```bash
sudo tailscale set --operator=$USER
```

Alternatively, grant passwordless access to the Tailscale binary:

```bash
echo "$USER ALL=(root) NOPASSWD: $(command -v tailscale)" | \
  sudo tee /etc/sudoers.d/smanager-tailscale
sudo chmod 0440 /etc/sudoers.d/smanager-tailscale
```

`start` and `restart` (re)create the Tailscale HTTPS serve when
`vpn.serve_https` is `true`; `stop` takes it down. If the VPN is disconnected it
is brought up first. Failures are reported as clean errors, and a failing VPN
serve never leaves the service itself down.

## Notes
- `metadata init` creates a new file.
- `metadata edit` modifies an existing file.
- `metadata validate` checks script paths and runtime-specific rules.
- Use command-specific `--help` for the latest options and examples.

