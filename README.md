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
- Update-availability detection in `status` (Docker digests, git, GitHub releases, composer, scripts).
- VPN integration (Tailscale provider support).
- Interactive metadata creation and editing, plus non-interactive `show`/`set`/`schema` with JSON output for panels and automation.
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
The `metadata` group provides both interactive workflows and non-interactive,
machine-friendly commands for service metadata files.

### Non-interactive commands (for panels / automation)
These commands never prompt and are safe to run without a TTY. With `--json`,
they write a single JSON document to stdout and send human errors to stderr.

```bash
smanager --config /path/smanager.yaml metadata show <service_id> --json
smanager --config /path/smanager.yaml metadata set <service_id> --json   # JSON on stdin
smanager --config /path/smanager.yaml metadata schema --json
```

#### `metadata show <service_id> [--json]`
Locates the service by `id` and returns its metadata file.

```json
{
  "id": "sonarr",
  "path": "/srv/services/sonarr/sd_info.json",
  "service_dir": "/srv/services/sonarr",
  "metadata": { "...": "raw file content, unknown keys preserved" }
}
```

Without `--json` it prints a readable review table.

#### `metadata set <service_id> [--file PATH] [--dry-run] [--json] [--allow-id-change]`
Reads a metadata JSON object from `--file` or stdin (default), validates it with
the same rules as `metadata validate`, and writes it atomically (temp file in the
same directory + `os.replace`) keeping a `<metadata>.bak` backup. The received
object is written verbatim so **unknown keys are preserved**.

- Validation failure: `{"success": false, "errors": ["..."]}` and exit code `1` (nothing is written).
- `metadata.id` must equal `<service_id>` unless `--allow-id-change` is passed.
- `--dry-run` validates and reports without writing (no backup either).
- Success: `{"success": true, "path": "...", "warnings": ["..."], "dry_run": false}`.

Errors such as a missing service, unreadable stdin, or an unknown config path are
also reported as `{"success": false, "errors": [...]}` when `--json` is used.

#### `metadata schema [--json]`
Prints a machine-readable description of the schema (sections, field paths and
types, enums, defaults, and per-runtime requirements) suitable for generating
forms in a UI.

```json
{
  "schema_version": 2,
  "enums": { "runtime_type": ["docker", "local", "php"], "update_strategy": ["..."], "version_strategy": ["..."], "package_manager": ["..."] },
  "scripts": { "actions": ["start", "stop", "restart", "status", "update", "check_update"] },
  "runtime_requirements": { "docker": { "required": ["docker.compose_file"], "unless": ["scripts.start", "scripts.stop"] } },
  "fields": [ { "path": "runtime.type", "type": "enum", "enum": "runtime_type", "required": true } ]
}
```

### Interactive commands
The following commands are interactive (require a TTY).

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

## Checking for updates
`status` can report whether a newer version is available. The check is opt-in
per service (a `version` section or `scripts.check_update`) and only runs when
`--updates` is passed:

```bash
smanager service status sonarr --updates
smanager all status --updates --json
```

The JSON status gains a nested `update` object:

```json
"update": {
  "available": true,
  "current": "1.2.0", "current_kind": "version", "current_digest": null,
  "latest": "1.3.1", "latest_kind": "version", "latest_digest": null,
  "source": "github", "error": null
}
```

`current`/`latest` are always strings. `current_kind`/`latest_kind` describe their
nature (`version`, `tag` or `digest`), and `current_digest`/`latest_digest` carry
the backing images digests when the strategy has them (currently Docker).

How the current/latest versions are obtained, by `version.latest.strategy`:

- `script` — `scripts.check_update` prints the latest version on stdout (`exit 0`).
- `command` — an inline command prints the latest version; `version.regex` extracts it.
- `github` — GitHub Releases API (`repo: owner/name`, or derived from a github git remote); `GITHUB_TOKEN`/`GH_TOKEN` raises the rate limit.
- `git` — compares the local checkout with the remote branch (`git fetch` + ancestry).
- `composer` — `composer outdated --direct --format=json`.
- `docker` — reports a human version and still decides `available` by comparing image digests (`docker buildx imagetools` / `regctl` / `crane`).
  - `current` prefers the local image OCI label `org.opencontainers.image.version` (falling back to `version`), then a version-like compose tag (e.g. `v1.2`, `1.2.3`, `2024.1`), and finally the local digest. Floating tags (`latest`, `stable`, `edge`, `nightly`, `dev`, `main`, `master`) and digest-pinned refs (`@sha256:`) are ignored.
  - `latest` prefers the remote OCI version label (`regctl image config` / `crane config` / `skopeo inspect`), falling back to the remote digest.
  - `current_kind`/`latest_kind` report `version`/`tag`/`digest` (or `null` when multiple images disagree), and `current_digest`/`latest_digest` always carry the digests used for the comparison.
- `package` — `apt`/`dnf`/`pacman`/`flatpak` using `package_manager` + `package`.
- `auto` — Docker uses the docker strategy; local/PHP detect a git remote (github → API) or a git/composer project.

```json
{
  "version": {
    "current_command": "sonarr --version",
    "regex": "v?([0-9]+\\.[0-9]+\\.[0-9]+)",
    "latest": { "strategy": "auto" }
  }
}
```

Current version resolution order: `version.current_command`, otherwise a git tag
(`git describe --tags`) / short SHA when the service is a git repo. If the current
version cannot be determined, `available` is `null` (unknown) instead of guessing.
Network/rate-limit/parse failures are reported in `update.error` and never break
`status`. The timeout can be tuned with `SMANAGER_CHECK_TIMEOUT` (seconds).

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
- `metadata validate` checks script paths and runtime/version-specific rules.
- Use command-specific `--help` for the latest options and examples.

