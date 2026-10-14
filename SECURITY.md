# Security model

SManager can manage privileged resources (systemd units, Docker, Tailscale). This
document describes the trust model of the privileged daemon (`smanagerd`) and how
to run it safely.

## Principles

1. **Privilege is concentrated in one component.** Only `smanagerd` runs with
   elevated rights; the `smanager` CLI is an unprivileged client that falls back
   to local execution when no daemon is available.
2. **Narrow API.** The daemon exposes typed operations over already-discovered
   services (`start|stop|restart|enable|disable|update|status|info` and their
   group/dependency/all variants). It never executes arbitrary commands supplied
   by the client.
3. **Validated input.** Clients only send `service_id`; the daemon resolves it
   against its own catalog. No client-provided paths or unit names.
4. **Local-only.** The socket is local (Unix domain socket). Do not expose it over
   the network.

## Socket access == privileged

The socket is `root:<group> 0660` (group `srvmgrs` by default, like
`/var/run/docker.sock`). **Any user in that group can perform every action the
daemon supports on every managed service.** Treat membership as equivalent to
granting the ability to manage those services as the daemon user. Add only
trusted users, and prefer a per-service allowlist where available.

## User-defined scripts and commands

Service metadata (`scripts.*`, update `command`/`script`, PHP commands) can run
arbitrary code. When the daemon runs as root, it executes these user-defined
processes with **dropped privileges** to the service's `runtime.sys_user` /
`sys_group`, so they never run as root. This is enabled by default in the daemon
(`--no-drop-scripts` disables it, at your own risk).

Privileged operations that are *not* user code (systemctl on the declared units,
`docker compose`, `git`/`composer` tooling, Tailscale) still run with the
daemon's privileges, which is why the API and input validation are narrow.

## Metadata trust

Metadata files are not trusted by themselves and never grant privileges. For
strict deployments, keep `services_root` and its metadata files owned by root and
not writable by unprivileged users, so an unprivileged user cannot inject scripts
that the daemon would run.

## Tampering resistance

- Exact `service_id` matching against the daemon catalog.
- Bounded frame size, per-request timeouts, per-connection threads, per-service
  locks.
- Structured audit logging for connections and actions (uid/pid/service/action).

## Reporting a vulnerability

Please open a private security advisory or a minimal, non-public report on the
project issue tracker with steps to reproduce. Do not include secrets or
production data.
