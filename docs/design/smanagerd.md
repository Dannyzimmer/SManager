# SManager privileged daemon design (`smanagerd`)

Status: accepted (design). Implementation tracked in phases at the end.

## Motivation

For a `local` (systemd) service, SManager currently runs `systemctl start/stop <unit>`
as the invoking user and falls back to `sudo -n systemctl ...`. That forces per-command
grants (sudoers NOPASSWD / polkit) or running the CLI with privileges: fragile, noisy
and unsuitable for a public package.

We move to the classic, safe pattern: **one privileged daemon with a narrow, validated
API**, and the CLI as an **unprivileged client** with a local fallback when the daemon is
not available.

## Goals / non-goals

Goals:

- Concentrate privilege in a single auditable component (`smanagerd`).
- Narrow, typed API over already-discovered services. Never arbitrary command execution
  from the client.
- Validate every input; no path traversal / injection.
- Group-based socket access (`root:srvmgrs 0660`), Docker/Podman style.
- Full backward compatibility: library and CLI keep working without the daemon.

Non-goals (for now): exposing the daemon over the network; converting services to systemd
user units; installing anything during `pip install`.

## Findings from the current code

- **Discovery**: `BaseGlobalManager.__init__` eagerly runs `ServiceDiscoverer.discover_services()`
  (`os.walk` + parse every `sd_info.json`). Duplicate ids are rejected. A single invalid file
  aborts discovery with `ValueError`. → The daemon must cache the catalog and report bad files
  without crashing.
- **Global API** (`GlobalManager`): `manage_service(id, action, dry_run)`, `manage_group`,
  `manage_by_dependency`, `manage_all`, `get_status`, `get_group_status`,
  `get_dependency_status`, `get_all_status`, `get_service(id)`, `get_service_manager(service)`.
  Actions: `start, stop, restart, update, enable, disable`. This is exactly the surface the
  daemon exposes.
- **Events**: `ManagerEvent` (`before/after/failed/skipped`) with a JSON-friendly `to_dict()`;
  `ManagerEventDispatcher.emit` is synchronous and isolates callback failures. → Reusable for
  progress **streaming** without touching the library.
- **Managers**: `LocalManager` runs `systemctl` (direct → `sudo -n`); `DockerManager` runs
  `docker compose ...`; `PhpManager` runs `shlex.split` commands.
- **Scripts/commands** (`scripts.*`, update `command|script|git|composer|auto`) run via
  `bash <script>` / `shlex.split` with `cwd`/`env`. **Main risk**: if the daemon is root,
  this is RCE as root.
- **Tailscale** (`vpn/providers/tailscale.py`) is a prior example of the client/service
  pattern (`tailscaled` + `tailscale set --operator`).
- **enable/disable** mutate `metadata.active` and write in place (preserves owner/mode);
  `metadata_ops.atomic_write_json` uses temp + `os.replace` (root would create root-owned files).
- **Config**: `GlobalConfig` (`services_root`, `vpn_provider`, `metadata_filename`,
  `systemd_privilege`); resolution via `cli/config.py`. Only the `smanager` entry point exists.
- **Deps**: `PyYAML, click, rich, InquirerPy, packaging`. The daemon can be stdlib-only.

## Architecture

```
            ┌──────────────────────────┐
  CLI/panel │  smanager (cliente)      │  sin privilegios
  no root   │  smanager/cli + client   │
            └───────────┬──────────────┘
                        │ Unix socket (NDJSON)
                        │ /run/smanager/smanagerd.sock  (root:srvmgrs 0660)
            ┌───────────▼──────────────┐
  root /    │  smanagerd (daemon)      │
  dedicado  │  protocol + authz + cat. │
            │  GlobalManager (reuso)   │
            └───┬───────┬───────┬──────┘
                │       │       │
           systemctl  docker  tailscale
            (units)  compose   serve
                │
        scripts.* → hijo con drop de privilegios (sys_user:sys_group)
```

New package `smanager/daemon/`: `protocol.py`, `server.py`, `client.py`, `authz.py`,
`catalog.py`, `install.py`, `__main__.py`. New command group `smanager daemon …`.
Entry point `smanagerd = smanager.daemon.server:main`.

## Transport and socket

- **Unix domain socket + NDJSON** (newline-delimited JSON) by default.
- Default socket `/run/smanager/smanagerd.sock`; override with `SMANAGER_SOCKET` or
  `global.daemon.socket`. User mode: `$XDG_RUNTIME_DIR/smanagerd.sock`.
- **Socket activation** via systemd `.socket` (`SocketMode=0660`, `SocketUser=root`,
  `SocketGroup=srvmgrs`, `Accept=no`); the daemon can also create the socket itself in
  manual/non-systemd mode.
- **D-Bus**: left as an optional future adapter behind the same `Transport` interface.

## Protocol

- Framing: **NDJSON**; one JSON object per line; strict parse; max frame size.
- Handshake: `hello` → `{protocol: 1, server_version, capabilities}`; version negotiated.
- Request: `{"id": 42, "method": "service.action", "params": {...}}`
- Response: `{"id": 42, "ok": true, "result": {...}}` or
  `{"id": 42, "ok": false, "error": {"code", "message", "details"}}`
- Event: `{"id": 42, "event": {"phase": "before", ...}}` (uses `ManagerEvent.to_dict()`),
  interleaved until the final response.
- Methods (narrow): `hello`, `daemon.ping`, `daemon.version`, `catalog.list`,
  `catalog.reload`, `service.info`, `service.status`, `service.action`, plus group/dependency/all
  variants.
- There is **no** `run_command` method. Per-request timeout, `cancel`, and connection close
  abort the operation.

## Authorization and trust model

- `SO_PEERCRED` → client `uid/gid/pid`; membership in the socket group (`srvmgrs`) is checked,
  plus an optional root-owned allowlist `/etc/smanager/daemon.yaml` (user/group → services/actions).
- Membership in the socket group means being able to manage services as the daemon
  (effectively root). This is documented loudly.
- The client only sends `service_id`; the daemon resolves it against **its** catalog (exact
  match) and uses `local.systemd_services` from **its** metadata. No client-provided paths or
  unit names (no path traversal / injection).
- Metadata does not by itself grant privilege; executing scripts through the daemon requires
  metadata to be root-owned and not writable by others.

## Daemon privilege and script execution

- **Privilege**: the daemon runs **as root** by default (system units, `docker`, `tailscale`).
  A dedicated `smanagerd` account + polkit rule for `org.freedesktop.systemd1.manage-units` +
  `docker` group + `tailscale set --operator` is supported and documented as the minimum-privilege
  alternative.
- **Scripts/commands**: strict plane separation.
  - Privileged systemd/docker/tailscale actions are executed by the daemon **directly, no shell**.
  - `scripts.*` and update `command|script` run in a **child with dropped privileges** to
    `runtime.sys_user:sys_group` (setgid+setuid, `NoNewPrivileges`, restricted `cwd`, sanitized
    `env`), and only when metadata is trusted (root-owned, not writable by others) and
    `daemon.allow_scripts=true`.
  - Otherwise the daemon refuses the action; the unprivileged CLI can still run it locally.

## State and concurrency

- The catalog is cached at startup; `catalog.reload` plus optional `inotify`/TTL refresh avoids
  re-crawling per request.
- `socketserver.ThreadingUnixStreamServer` (stdlib): one thread per connection. Operations are
  synchronous and events are emitted on that same thread → direct socket writes.
- A **lock per service** prevents concurrent start/stop; `all/group/dependency` take locks in a
  deterministic order; a cap limits concurrent privileged operations.
- `enable/disable` only mutates `active`, preserving the original uid/gid/mode (stat + `fchown`/
  `fchmod` of the temp before `os.replace`, or in-place). `metadata set` is **not** exposed by the
  daemon.

## Installation / packaging

- `smanager daemon install [--group srvmgrs] [--user root] [--socket ...]` (root, interactive
  sudo): creates the group, `.socket` + `.service`, enables the socket. Idempotent, with
  `--dry-run` printing artifacts. `uninstall`, `status`, `logs`.
- **Never** during `pip install` / in `pyproject`.
- Ship unit templates as package data; entry point `smanagerd`.

## Client and fallback

- `smanager` chooses: if `--daemon`, or `SMANAGER_SOCKET`/the socket exists → client; else local
  execution (current behavior, including `sudo -n`). Flags `--daemon/--no-daemon`,
  `global.daemon.enabled/socket`. Clear messages; structured errors with `--json`.

## Security / threat model

- **A1** user outside the group → denied via `SO_PEERCRED`.
- **A2** user inside the group → can manage services (≈root if scripts ran as root; mitigated by
  the privilege drop). Documented; audit; optional allowlist.
- **A3** tampered metadata → grants no privilege; privileged actions require trusted metadata.
- **TOCTOU/symlinks**: `O_NOFOLLOW`, operate on fds, `realpath` within `services_root`.
- **DoS**: max frame size, timeouts, max connections/ops, rate limits.
- **Audit**: JSON log (journald/stdout): `ts, uid, pid, method, service_id, action, result, error`.
- No secrets stored; versioned protocol; no arbitrary exec.

## Decisions (A–L)

| # | Decision | Alternative (rejected) | Why |
|---|---|---|---|
| A | Unix socket + NDJSON; D-Bus optional later behind an interface | D-Bus from the start | stdlib, no deps, debuggable; D-Bus adds complexity |
| B | systemd `.socket` (0660 root:srvmgrs); daemon creates it in manual mode | daemon always creates it | no races; systemd manages perms |
| C | daemon root by default; dedicated account + polkit as an option | dedicated account always | system units/docker/tailscale need privilege |
| D | separate privileged plane (systemd/docker, no shell) from scripts (drop to `sys_user`, trusted metadata) | scripts as root / disable scripts | least privilege + usefulness |
| E | socket group (≈root, documented) + optional root-owned allowlist | group only | Docker-like + strict deployments |
| F | NDJSON req/resp + `ManagerEvent` streaming + `hello` + timeouts/cancel | msgpack / binary | stdlib; reuses events |
| G | cached catalog + `reload`; ThreadingUnixStreamServer; per-service lock | re-crawl per request | performance and consistency |
| H | daemon only writes `active`, preserving owner/mode; `metadata set` stays local | atomic root-owned write | do not break file ownership |
| I | `smanager daemon install/uninstall/status` with explicit sudo | packaging scripts | PyPI must not touch the system |
| J | auto-detect socket + local fallback; `--daemon/--no-daemon`, env/config | daemon mandatory | compatibility, zero-config |
| K | threat model + audit + limits + `O_NOFOLLOW`/TOCTOU | — | explicit security |
| L | socket **local-only**; remote stays over SSH | expose to network | out of scope / security |

## Phased plan

- **Phase 0**: this document; version `tests/` (remove from `.gitignore`).
- **Phase 1** (feature-flag, CLI untouched): `protocol.py` (NDJSON, `hello`, correlation,
  timeouts) + minimal `server.py` (`start/stop/restart/status`) reusing `GlobalManager` +
  `client.py` + `smanagerd` entry point. Tests: framing, correlation, errors, timeout,
  daemon-down → reconnect.
- **Phase 2**: `authz.py` (`SO_PEERCRED`/group, allowlist), strict id validation, JSON audit,
  event streaming. Tests: credentials/group, validation, concurrency/locks, audit.
- **Phase 3**: `install.py` + `smanager daemon install|uninstall|status` (group + units + socket
  activation). Tests: idempotent install, dry-run, socket perms.
- **Phase 4**: remaining actions (`enable/disable/update/info`, group/dependency/all) and CLI
  migration to client with fallback. Tests: client↔local parity, fallback without socket.
- **Phase 5**: hardening (privilege drop to `runtime.sys_user` for `scripts.*`/update with
  trusted metadata, `NoNewPrivileges`, `CapabilityBoundingSet`, polkit/min privilege),
  `SECURITY.md`, README/`--help`. Tests: scripts as `sys_user`, rejection with untrusted metadata.
