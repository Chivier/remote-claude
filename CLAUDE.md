# Codecast - Project Guide

## Project Overview

Codecast is a bot-based system that lets users interact with Claude CLI on remote machines through Discord, Telegram, and Lark. It follows a **Head Node + Daemon** architecture: the Head Node (Python) runs locally as a chat bot, connects to remote machines via SSH, and communicates with a Daemon (Rust) running on each remote machine.

## Project Structure

```
codecast/
├── CLAUDE.md                  # This file - project overview
├── .claude/
│   └── rules/                 # Detailed development rules
│       ├── core.md            # Code conventions, testing, known pitfalls
│       ├── config.md          # Configuration format and rules
│       └── release.md         # Version management and release process
│
├── src/
│   ├── head/                  # Head Node (Python) - local bot + SSH orchestrator
│   │   ├── cli.py             # CLI entry point: argparse, subcommand dispatch
│   │   ├── main.py            # Head node entry: loads config, starts bots, shutdown
│   │   ├── config.py          # Config loader: YAML parsing, env var expansion
│   │   ├── engine.py          # Core command engine: session lifecycle, message routing
│   │   ├── ssh_manager.py     # SSH connections, tunnels, daemon deployment
│   │   ├── session_router.py  # SQLite-backed session registry
│   │   ├── daemon_client.py   # JSON-RPC + SSE client for daemon communication
│   │   ├── message_formatter.py # Message splitting, tool_use batching
│   │   ├── tui/               # Interactive TUI (Textual)
│   │   └── webui/             # Web UI (aiohttp)
│   │
│   └── daemon/                # Remote Agent Daemon (Rust)
│       ├── main.rs            # Axum HTTP server, port allocation
│       ├── server.rs          # JSON-RPC router, SSE streaming
│       ├── session_pool.rs    # Session registry and per-message CLI execution
│       ├── message_queue.rs   # Per-session message buffering
│       ├── skill_manager.rs   # Runtime sync from ~/.codecast/skills
│       └── types.rs           # All type definitions
│
├── scripts/
│   ├── bump-version.sh        # Version bump across all files
│   ├── lint.sh                # Lint checker/fixer (ruff + clippy + cargo fmt)
│   └── install.sh             # Installation script
│
├── docs/                      # Documentation (mdbook, bilingual en/zh)
│   ├── book.toml              # mdbook configuration
│   ├── build-docs.sh          # Multi-language doc build script
│   ├── en/                    # English documentation
│   ├── zh/                    # Chinese documentation
│   └── ai/                    # AI-readable architecture and runbooks
│
├── skills/                    # Shared skills shipped with the project
│
└── tests/                     # Python tests (812+ tests, pytest + pytest-asyncio)
```

## Architecture

```
User (Discord/Telegram/Lark)
      │
      ▼
┌──────────────┐
│  Head Node   │  Python (local machine)
│  (bot_*.py)  │  - Bot adapters (Discord, Telegram, Lark)
│  engine.py   │  - Command dispatch, session lifecycle
└──────┬───────┘
       │ SSH tunnel (asyncssh) OR direct localhost
       ▼
┌──────────────┐
│   Daemon     │  Rust (remote machine)
│  server.rs   │  - Axum HTTP on 127.0.0.1:9100
│  session-pool│  - Per-message CLI subprocesses + resume state
│  msg-queue   │  - Message buffering for reconnect
└──────┬───────┘
       │ stdout stream-json
       ▼
┌──────────────┐
│  AI CLI      │  Claude / Codex / Gemini / OpenCode
└──────────────┘
```

## Runtime instructions and skills

Repo-local `.claude/rules/` contains development guidance for this codebase. Runtime instructions and shared skills are synced separately:

- The daemon copies instruction files and optional skills from `~/.codecast/skills`
- For Claude sessions, the instruction file is `CLAUDE.md`
- Claude sessions may also sync `.claude/skills/` into the target project
- Other CLIs use their own instruction filenames and may not use `.claude/skills/`

See `src/daemon/skill_manager.rs` and `src/daemon/cli_adapter/mod.rs` for the actual sync behavior.

## Quick Reference

### Setup & Run

```bash
pip install codecast
cp config.example.yaml ~/.codecast/config.yaml
codecast                    # Start head node
```

### Development

```bash
python -m pytest tests/ -v          # Run tests
./scripts/lint.sh --fix             # Lint + auto-fix
cargo build --release               # Build daemon
./scripts/deploy-test.sh            # Deploy to test env
```

### Release

```bash
./scripts/bump-version.sh X.Y.Z    # Bump all version files
# See .claude/rules/release.md for full release flow
```

## Rules & Conventions

Detailed rules are in `.claude/rules/`:
- **[core.md](.claude/rules/core.md)** — Code conventions, testing, known pitfalls
- **[config.md](.claude/rules/config.md)** — Configuration format, permission modes
- **[release.md](.claude/rules/release.md)** — Version management, CI build matrix, release flow

## Key Design Decisions

1. **Per-message CLI execution** — each send spawns a fresh CLI subprocess, and conversation continuity is preserved with `--resume`
2. **SSH tunnels** — daemon binds `127.0.0.1` only, SSH provides authentication
3. **Localhost mode** — auto-detected, skips SSH entirely for local machines
4. **SSE streaming** — `session.send` streams via SSE, other RPCs use standard JSON
5. **Session lifecycle** — `active → detached → destroyed`
6. **Message queue** — buffers during busy/disconnect, enables reconnect without data loss
7. **Tool call batching** — consecutive tool_use events compressed into single summary (default 15)

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start <machine> <path>` | Create new session on remote machine |
| `/resume <name>` | Resume a detached session |
| `/exit` | Detach (process keeps running) |
| `/ls machine\|session` | List machines or sessions |
| `/mode <auto\|code\|plan\|ask>` | Switch permission mode |
| `/status` | Current session info |
| `/health [machine]` | Daemon health check |
| `/update` | Git pull + restart (admin only) |

## RPC Methods (Daemon API)

| Method | Response | Description |
|--------|----------|-------------|
| `session.create` | JSON | Register a new daemon session |
| `session.send` | SSE stream | Send message, stream response |
| `session.resume` | JSON | Restore resume state for a detached session |
| `session.destroy` | JSON | Kill active work and remove the session |
| `session.list` | JSON | List all sessions |
| `health.check` | JSON | Health + uptime |
