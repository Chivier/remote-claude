# Codex CLI Support Design

**Date:** 2026-03-19
**Status:** Draft
**Scope:** Add OpenAI Codex CLI as a second supported CLI backend alongside Claude CLI, with a trait-based adapter architecture designed for future CLI extensibility (OpenCode, Kiro, etc.)

## Requirements

- **Per-session CLI selection**: Same machine can run Claude and Codex sessions simultaneously
- **Authentication**: Rely on remote machine's pre-configured environment (OPENAI_API_KEY or `codex login`)
- **Command UX**: `/start <machine> <path> --cli codex` or `--codex` shorthand; defaults to claude
- **MVP scope**: Core session lifecycle only (create, send, stream, resume, destroy, permission modes). No Codex-specific features (--image, --add-dir, --ephemeral)

## Architecture: Daemon-Side CliAdapter Trait

### Trait Definition

```rust
// src/daemon/cli_adapter/mod.rs

/// CliAdapter is NOT stored per-session. A fresh instance is created at the
/// start of each `run_cli_process()` call via `create_adapter()`. This ensures
/// per-run state (e.g., CodexAdapter's cumulative text tracker) is always clean.
pub trait CliAdapter: Send + Sync {
    /// CLI name identifier ("claude", "codex")
    fn name(&self) -> &str;

    /// Build command for first execution
    fn build_command(
        &self,
        message: &str,
        mode: PermissionMode,
        cwd: &Path,
    ) -> Command;

    /// Build command for session resume
    fn build_resume_command(
        &self,
        message: &str,
        mode: PermissionMode,
        cwd: &Path,
        session_id: &str,
    ) -> Command;

    /// Parse one JSON-lines output line → StreamEvent.
    /// For stateful adapters (e.g., CodexAdapter tracking cumulative text),
    /// this method uses interior mutability (Mutex/Cell) to track per-run state.
    fn parse_output_line(&self, line: &str) -> Option<StreamEvent>;

    /// Extract session/thread ID from output (called once on first message)
    fn extract_session_id(&self, line: &str) -> Option<String>;

    /// Instructions file name for skill sync
    fn instructions_file(&self) -> &str;

    /// Log level for stderr output (Claude: error, Codex: info)
    fn stderr_log_level(&self) -> log::Level;
}
```

### Why 4+ Methods Instead of 2

- `build_command` vs `build_resume_command`: Claude uses `--resume` flag, Codex uses `exec resume` subcommand — argument positions are structurally different
- `parse_output_line` vs `extract_session_id`: Session ID extraction is a one-time operation (first message), parsing runs on every line
- `instructions_file`: Claude syncs `CLAUDE.md`, Codex syncs `AGENTS.md`
- `stderr_log_level`: Codex sends progress to stderr (normal), Claude sends errors to stderr

### Adapter Factory

```rust
/// Called at the start of each run_cli_process() invocation — NOT stored per-session.
/// This guarantees CodexAdapter's cumulative text state is fresh for each turn.
pub fn create_adapter(cli_type: &str) -> Box<dyn CliAdapter> {
    match cli_type {
        "codex" => Box::new(CodexAdapter::new()),
        _ => Box::new(ClaudeAdapter),  // default
    }
}
```

### Adapter Lifecycle

The adapter is **created fresh per `run_cli_process()` call**, not stored in `InternalSession`. The session stores only `cli_type: String`, and the factory is called each time a message is processed. This ensures:
- `CodexAdapter`'s cumulative text tracking state is reset between turns
- No stale state from a previous turn corrupts delta computation
- `ClaudeAdapter` (stateless) is unaffected

### File Structure

```
src/daemon/
  cli_adapter/
    mod.rs          # CliAdapter trait + factory
    claude.rs       # ClaudeAdapter (extracted from current session_pool.rs + types.rs)
    codex.rs        # CodexAdapter (new)
    opencode.rs     # future
    kiro.rs         # future
```

## Codex CLI Interface

### Command Construction

```bash
# First message
codex exec --json --full-auto --cd ~/myproject "the user message"

# Resume session
codex exec resume <thread_id> --json --full-auto --cd ~/myproject "follow-up message"
```

Key differences from Claude CLI:
- Subcommand-based (`exec`) rather than flag-based (`--print`)
- Resume is a subcommand (`exec resume <id>`) not a flag (`--resume <id>`)
- JSON output via `--json` not `--output-format stream-json`
- No `--include-partial-messages` equivalent (implicit in `--json`)
- No `--verbose` equivalent

### Permission Mode Mapping

| Codecast Mode | Claude CLI Flags | Codex CLI Flags |
|---|---|---|
| `auto` | `--dangerously-skip-permissions` | `--full-auto` |
| `code` | acceptEdits | `--full-auto` |
| `plan` | read-only | `--sandbox read-only` |
| `ask` | confirm everything | `--sandbox read-only --approval-policy on-failure` |

Note: `auto` and `code` both map to `--full-auto` on Codex side. Claude's `code` mode (auto-approve edits only) has no exact Codex equivalent.

**Important**: Codex CLI flag names must be verified against `codex exec --help` before implementation. The flags above are based on publicly documented Codex CLI interfaces but may vary by version. The Codex CLI uses `--approval-policy` (not `--ask-for-approval`) with values `never`, `on-failure`, and `unless-allow-listed`.

## Output Event Mapping

Codex uses a `thread > turn > item` event hierarchy. All events are mapped to the existing `StreamEvent` enum without adding new variants.

| Codex Event | StreamEvent | Notes |
|---|---|---|
| `thread.started` | `System { subtype: "init" }` | Extract `thread_id` as session ID |
| `turn.started` | (ignored) | No corresponding semantic |
| `item.started` (agent_message) | (ignored) | Wait for updated |
| `item.updated` (agent_message) | `Partial { content }` | Incremental text delta |
| `item.completed` (agent_message) | `Text { content }` | Complete text block |
| `item.started` (command_execution) | `ToolUse { tool: "bash" }` | Command start |
| `item.completed` (command_execution) | `ToolUse { tool: "bash", message }` | Command done with output |
| `item.started` (file_change) | `ToolUse { tool: "edit" }` | File edit start |
| `item.completed` (file_change) | `ToolUse { tool: "edit", message }` | Edit done |
| `item.*` (mcp_tool_call) | `ToolUse { tool: <name> }` | MCP tool call |
| `turn.completed` | `Result { session_id }` | Turn done, includes token usage |
| `turn.failed` | `Error { message }` | Error |
| `error` | `Error { message }` | Top-level error |

### Incremental Text Handling

Codex `item.updated` events carry cumulative state, not pure deltas. `CodexAdapter` tracks the last seen text length via interior mutability (`Cell<usize>`) and emits only the new portion as `Partial { content }`. Since the adapter is created fresh per `run_cli_process()` call, this state automatically resets between turns.

### Result Event and Thread ID

When `CodexAdapter` processes a `thread.started` event, it captures the `thread_id` internally (via `Cell<Option<String>>`). When it later processes `turn.completed`, it emits `Result { session_id: Some(captured_thread_id) }`. This ensures the Head Node receives the thread ID in the `Result` event and can persist it to SQLite for future `/resume` calls. Without this, Codex session resume would silently fail.

### Tool Name Normalization

Codex tool types are normalized to match Claude's conventions so the Head Node sees consistent tool names:
- `command_execution` → `bash`
- `file_change` → `edit`
- `mcp_tool_call` → actual tool name from the event

## RPC Protocol Changes

### session.create — New Parameter

```json
{
    "method": "session.create",
    "params": {
        "path": "~/myproject",
        "mode": "auto",
        "cli_type": "codex"     // NEW: optional, defaults to "claude"
    }
}
```

All other RPC methods (send, resume, destroy, interrupt, list, set_mode, queue_stats, reconnect, health.check) remain unchanged. The `cli_type` is stored in `SessionState` and used automatically for all subsequent operations on that session.

### SessionState Change

```rust
pub struct SessionState {
    pub id: String,
    pub cli_type: String,        // NEW: "claude" | "codex"
    pub sdk_session_id: Option<String>,
    pub mode: PermissionMode,
    pub project_path: String,
    // ... rest unchanged
}
```

## Head Node Changes

### daemon_client.py

`create_session()` gains an optional `cli_type` parameter:

```python
async def create_session(self, path, mode=None, cli_type="claude"):
    params = {"path": path, "cli_type": cli_type}
    if mode:
        params["mode"] = mode
    return await self._call("session.create", params)
```

### engine.py

`cmd_start()` extracts `--cli`/`--codex` from the `args` list (note: the actual method is `cmd_start`, not `_cmd_start`, and it receives `args: list[str]`):

```python
async def cmd_start(self, channel_id: str, args: list[str], ...):
    # Extract --cli <type> or --codex from args
    cli_type = "claude"  # default
    if "--codex" in args:
        args.remove("--codex")
        cli_type = "codex"
    elif "--cli" in args:
        idx = args.index("--cli")
        cli_type = args[idx + 1]
        del args[idx:idx + 2]
    # ... existing machine/path parsing ...
    result = await client.create_session(path, mode, cli_type=cli_type)
```

**`/clear` and `/new` regression**: These commands internally call `cmd_start()` to re-create sessions. They must read `cli_type` from the existing session in `session_router` and pass it through, so a Codex session stays Codex after `/clear` or `/new`.

### bot_base.py / bot_discord.py

`/start` command parsing extracts CLI type:

```
/start gpu-server ~/myproject              → cli_type="claude" (default)
/start gpu-server ~/myproject --cli codex  → cli_type="codex"
/start gpu-server ~/myproject --codex      → cli_type="codex" (shorthand)
```

Discord slash command adds an optional `cli` choice parameter with values `claude` and `codex`.

### session_router.py

Both `sessions` and `session_log` tables need migration (session_log stores historical sessions used by `/resume`):

```sql
ALTER TABLE sessions ADD COLUMN cli_type TEXT DEFAULT 'claude';
ALTER TABLE session_log ADD COLUMN cli_type TEXT DEFAULT 'claude';
```

The `Session` dataclass gains a `cli_type: str = "claude"` field, and `_row_to_session()` is updated to read it. Without migrating `session_log`, resuming a detached Codex session would silently re-create it as Claude.

### message_formatter.py

`/status` and `/ls session` output includes CLI type indicator.

## Skill Sync

`skill_manager.rs` gains a new method signature:

```rust
// Current: sync_to_project(path: &Path) — always syncs CLAUDE.md + .claude/skills/
// New:     sync_to_project(path: &Path, cli_type: &str) — syncs based on CLI type
pub fn sync_to_project(&self, path: &Path, cli_type: &str) -> Result<()> {
    let adapter = create_adapter(cli_type);
    let instructions_file = adapter.instructions_file();
    // Sync instructions_file to project root
    // For "claude": also sync .claude/skills/
    // For "codex": no skills dir sync in v1
}
```

- Claude sessions: sync `CLAUDE.md` + `.claude/skills/` to project directory
- Codex sessions: sync `AGENTS.md` to project directory (no `.codex/` skills in v1)

In `server.rs`, `handle_create_session()` passes `cli_type` (parsed from RPC params) to `skill_manager.sync_to_project(path, &cli_type)`.

## File Change Summary

| File | Change |
|---|---|
| `src/daemon/cli_adapter/mod.rs` | **New** — CliAdapter trait + factory |
| `src/daemon/cli_adapter/claude.rs` | **New** — Extract from session_pool.rs + types.rs |
| `src/daemon/cli_adapter/codex.rs` | **New** — Codex implementation |
| `src/daemon/session_pool.rs` | **Modify** — Use CliAdapter, add cli_type to SessionState |
| `src/daemon/server.rs` | **Modify** — Parse cli_type in session.create |
| `src/daemon/types.rs` | **Modify** — Remove `convert_claude_message` (moved to adapter), remove `PermissionMode::to_cli_flags()` (each adapter handles its own flags), add `cli_type` to `SessionInfo` struct |
| `src/daemon/skill_manager.rs` | **Modify** — Use instructions_file() from adapter |
| `src/head/daemon_client.py` | **Modify** — create_session adds cli_type |
| `src/head/engine.py` | **Modify** — `cmd_start` parses --cli/--codex from args, `cmd_clear`/`cmd_new` carry cli_type from existing session |
| `src/head/bot_base.py` | **Modify** — /start parses --cli/--codex |
| `src/head/bot_discord.py` | **Modify** — Slash command adds cli choice |
| `src/head/session_router.py` | **Modify** — Both `sessions` and `session_log` tables add cli_type column, `Session` dataclass updated |
| `src/head/message_formatter.py` | **Modify** — /status and /ls show cli_type |

## Testing Strategy

### Daemon (Rust)

- `CodexAdapter` unit tests with sample Codex JSON-lines output
- `ClaudeAdapter` regression tests ensuring no behavior change after extraction
- `create_adapter()` factory routing tests
- Incremental text delta computation tests (cumulative → delta)

### Head Node (Python)

- `daemon_client.create_session()` parameter passing tests
- `/start --cli codex` and `--codex` argument parsing tests
- `session_router` cli_type column migration and CRUD tests
- `/status` and `/ls session` CLI type display tests

## Out of Scope (v1)

- Codex-specific features: `--image`, `--add-dir`, `--ephemeral`, `--output-schema`
- OpenCode / Kiro adapters (architecture supports them, not implemented)
- Config-level API key management (relies on remote machine environment)
- `.codex/` skills directory sync
- Codex profile support (`--profile`)
- `codex fork` session forking
