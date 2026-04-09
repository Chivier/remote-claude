# Codecast Architecture (AI Reference)

This document provides a machine-readable architecture overview for AI agents working on the Codecast codebase.

## System Overview

Codecast is a **Head Node + Daemon** distributed system:
- **Head Node** (Python): local bot process connecting Discord/Telegram/Lark users to remote machines
- **Daemon** (Rust): remote agent managing per-message CLI subprocesses on target machines

## Data Flow

```
User Message → Bot Adapter → Engine → SSH Manager → Daemon Client
                                                        ↓ (JSON-RPC)
                                                    Daemon Server
                                                        ↓
                                                    Session Pool
                                                        ↓ (spawn per message)
                                             Claude / Codex / Gemini / OpenCode
                                                        ↓ (stdout stream-json)
                                                    Stream Events
                                                        ↓ (SSE)
User ← Bot Adapter ← Message Formatter ← Engine ← Daemon Client
```

## Component Map

### Head Node (`src/head/`)

| Component | File | Responsibility |
|-----------|------|----------------|
| CLI | `cli.py` | Entry point, argparse, subcommand dispatch |
| Main | `main.py` | Config loading, bot lifecycle, shutdown |
| Engine | `engine.py` | Command dispatch, session lifecycle, message routing |
| SSH Manager | `ssh_manager.py` | SSH connections, tunnels, daemon deploy, localhost mode |
| Session Router | `session_router.py` | SQLite session registry, channel→session mapping |
| Daemon Client | `daemon_client.py` | JSON-RPC client, SSE stream parsing |
| Message Formatter | `message_formatter.py` | Message splitting, tool batching, status display |
| Platform Adapters | `platform/` | Discord / Telegram / Lark integrations |
| Config | `config.py` | YAML parsing, env var expansion, SSH config import |

### Daemon (`src/daemon/`)

| Component | File | Responsibility |
|-----------|------|----------------|
| Server | `main.rs` + `server.rs` | Axum HTTP, JSON-RPC routing, SSE streaming |
| Session Pool | `session_pool.rs` | Session registry, per-message CLI execution |
| Message Queue | `message_queue.rs` | User/response buffering for reconnect |
| Skill Manager | `skill_manager.rs` | Runtime instruction/skills sync to project dirs |
| CLI Adapters | `cli_adapter/*.rs` | CLI-specific command construction and output parsing |
| Types | `types.rs` | RPC, session, and stream event definitions |
| Auth | `auth.rs` | Token-based middleware |
| TLS | `tls.rs` | Certificate generation/loading |

## Key Design Decisions

1. **Per-message CLI execution** — each send spawns a fresh subprocess and uses `--resume` (or equivalent) for continuity
2. **SSH tunnels** — daemon binds `127.0.0.1` only by default, SSH provides access control
3. **Localhost mode** — auto-detected, skips SSH entirely for local machines
4. **SSE streaming** — `session.send` streams via SSE; most other RPCs use JSON
5. **Session lifecycle** — active → detached → destroyed
6. **Message queue** — buffers during busy/disconnect and supports replay on reconnect
7. **Tool call batching** — consecutive tool events can be summarized for chat UX

## RPC Protocol

All methods use JSON-RPC over HTTP POST to the daemon `/rpc` endpoint.

| Method | Response Type | Purpose |
|--------|--------------|---------|
| `session.create` | JSON | Register a new session |
| `session.send` | SSE stream | Send message, stream response |
| `session.resume` | JSON | Restore resume state |
| `session.destroy` | JSON | Kill work and remove session |
| `session.list` | JSON | List sessions |
| `session.set_mode` | JSON | Change permission mode |
| `session.set_model` | JSON | Change session model |
| `health.check` | JSON | Health + uptime |
| `monitor.sessions` | JSON | Detailed per-session state |
