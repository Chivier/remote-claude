# Multi-CLI Adapter Support Design

**Date:** 2026-03-19
**Status:** Draft
**Scope:** Support multiple CLI backends (Claude, Codex, Gemini, OpenCode) via a trait-based adapter architecture. All four CLIs share the same Head Node infrastructure; only the Daemon-side adapter differs per CLI.

## Requirements

- **Per-session CLI selection**: Same machine can run sessions from different CLIs simultaneously
- **Authentication**: Rely on remote machine's pre-configured environment (API keys, `codex login`, `gemini auth`, `opencode auth login`)
- **Command UX**: `/start <machine> <path> --cli <type>` or `--<type>` shorthand; defaults to claude
- **MVP scope**: Core session lifecycle only (create, send, stream, resume, destroy, permission modes). No CLI-specific advanced features
- **Parallelizable implementation**: Shared infrastructure implemented once; per-CLI adapters are independent and can be developed in parallel

## Supported CLIs

| CLI | Command | Package / Install | Instructions File |
|-----|---------|-------------------|-------------------|
| Claude | `claude` | `npm i -g @anthropic-ai/claude-code` | `CLAUDE.md` |
| Codex | `codex` | `npm i -g @openai/codex` | `AGENTS.md` |
| Gemini | `gemini` | `npm i -g @google/gemini-cli` | `GEMINI.md` |
| OpenCode | `opencode` | `go install` or binary | `AGENTS.md` |

## Architecture: Daemon-Side CliAdapter Trait

### Trait Definition

```rust
// src/daemon/cli_adapter/mod.rs

/// CliAdapter is NOT stored per-session. A fresh instance is created at the
/// start of each `run_cli_process()` call via `create_adapter()`. This ensures
/// per-run state (e.g., cumulative text trackers) is always clean.
pub trait CliAdapter: Send + Sync {
    /// CLI name identifier ("claude", "codex", "gemini", "opencode")
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

    /// Parse one JSON-lines output line → Vec<StreamEvent>.
    /// Returns Vec because one line may produce multiple events (e.g., Claude
    /// assistant message with text + multiple tool_use blocks).
    /// For stateful adapters (e.g., cumulative text tracking),
    /// this method uses interior mutability (Mutex/Cell) to track per-run state.
    fn parse_output_line(&self, line: &str) -> Vec<StreamEvent>;

    /// Extract session/thread ID from output (called once on first message)
    fn extract_session_id(&self, line: &str) -> Option<String>;

    /// Instructions file name for skill sync
    fn instructions_file(&self) -> &str;

    /// Skills directory to sync (e.g., ".claude/skills/"), if any
    fn skills_dir(&self) -> Option<&str>;

    /// Log level for stderr output
    fn stderr_log_level(&self) -> log::Level;
}
```

**Changes from the original Codex-only design:**
- `parse_output_line` now returns `Vec<StreamEvent>` instead of `Option<StreamEvent>` — Claude's `assistant` messages produce multiple events (tool_use + text) from a single line. A Vec handles this cleanly.
- Added `skills_dir()` method — Claude syncs `.claude/skills/`, others don't have a skills directory.

### Why 5+ Methods

| Method | Reason |
|--------|--------|
| `build_command` vs `build_resume_command` | Resume mechanics differ: Claude uses `--resume` flag, Codex uses `exec resume` subcommand, Gemini uses `--resume`, OpenCode uses `--session` |
| `parse_output_line` | Each CLI has a different JSON event schema |
| `extract_session_id` | Session ID lives in different event types per CLI |
| `instructions_file` | Claude → `CLAUDE.md`, Gemini → `GEMINI.md`, Codex/OpenCode → `AGENTS.md` |
| `skills_dir` | Only Claude has `.claude/skills/` |
| `stderr_log_level` | Some CLIs send progress to stderr (normal), others send only errors |

### Adapter Factory

```rust
pub fn create_adapter(cli_type: &str) -> Box<dyn CliAdapter> {
    match cli_type {
        "codex" => Box::new(CodexAdapter::new()),
        "gemini" => Box::new(GeminiAdapter::new()),
        "opencode" => Box::new(OpenCodeAdapter::new()),
        _ => Box::new(ClaudeAdapter),  // default
    }
}
```

### Adapter Lifecycle

The adapter is **created fresh per `run_cli_process()` call**, not stored in `InternalSession`. The session stores only `cli_type: String`, and the factory is called each time a message is processed. This ensures:
- Stateful adapters (CodexAdapter, GeminiAdapter with cumulative text tracking) reset between turns
- No stale state from a previous turn corrupts delta computation
- Stateless adapters (ClaudeAdapter) are unaffected

### File Structure

```
src/daemon/
  cli_adapter/
    mod.rs          # CliAdapter trait + factory + shared helpers
    claude.rs       # ClaudeAdapter (extracted from current session_pool.rs + types.rs)
    codex.rs        # CodexAdapter
    gemini.rs       # GeminiAdapter
    opencode.rs     # OpenCodeAdapter
```

---

## Shared Infrastructure (Implement Once)

The following components are **CLI-agnostic** and only need to be implemented once. They form the foundation that all four adapters build upon.

### Daemon-Side Shared

| Component | Change |
|-----------|--------|
| `cli_adapter/mod.rs` | CliAdapter trait definition + `create_adapter()` factory |
| `session_pool.rs` | Use `CliAdapter` via factory, add `cli_type` to `InternalSession` |
| `server.rs` | Parse `cli_type` from `session.create` RPC params |
| `types.rs` | Remove `convert_claude_message()` (moved to adapter), remove `PermissionMode::to_cli_flags()`, add `cli_type` to `SessionInfo` |
| `skill_manager.rs` | Use `instructions_file()` + `skills_dir()` from adapter |

### Head Node Shared (Python)

| Component | Change |
|-----------|--------|
| `daemon_client.py` | `create_session()` gains `cli_type` parameter |
| `engine.py` | `cmd_start()` parses `--cli <type>` from args; `cmd_clear`/`cmd_new` carry `cli_type` from existing session |
| `bot_discord.py` | Slash command adds `cli` choice parameter (claude/codex/gemini/opencode) |
| `session_router.py` | `cli_type` column in `sessions` + `session_log` tables; `Session` dataclass updated |
| `message_formatter.py` | `/status` and `/ls session` show CLI type indicator |

### RPC Protocol Changes

#### session.create — New Parameter

```json
{
    "method": "session.create",
    "params": {
        "path": "~/myproject",
        "mode": "auto",
        "cli_type": "gemini"     // NEW: optional, defaults to "claude"
    }
}
```

All other RPC methods remain unchanged. The `cli_type` is stored in `SessionState` and used automatically for all subsequent operations.

#### SessionState Change

```rust
pub struct SessionState {
    pub id: String,
    pub cli_type: String,        // NEW: "claude" | "codex" | "gemini" | "opencode"
    pub sdk_session_id: Option<String>,
    pub mode: PermissionMode,
    pub project_path: String,
    // ... rest unchanged
}
```

### Head Node Changes (Detail)

#### daemon_client.py

```python
async def create_session(self, path, mode=None, cli_type="claude"):
    params = {"path": path, "cli_type": cli_type}
    if mode:
        params["mode"] = mode
    return await self._call("session.create", params)
```

#### engine.py

```python
async def cmd_start(self, channel_id: str, args: list[str], ...):
    cli_type = "claude"  # default
    # Check shorthand flags first
    for shorthand in ("--codex", "--gemini", "--opencode"):
        if shorthand in args:
            args.remove(shorthand)
            cli_type = shorthand.lstrip("-")
            break
    # Then check --cli <type>
    if "--cli" in args:
        idx = args.index("--cli")
        cli_type = args[idx + 1]
        del args[idx:idx + 2]
    # ... existing machine/path parsing ...
    result = await client.create_session(path, mode, cli_type=cli_type)
```

**`/clear` and `/new` regression**: Must read `cli_type` from existing session in `session_router` and pass it through.

#### session_router.py

```sql
ALTER TABLE sessions ADD COLUMN cli_type TEXT DEFAULT 'claude';
ALTER TABLE session_log ADD COLUMN cli_type TEXT DEFAULT 'claude';
```

The `Session` dataclass gains `cli_type: str = "claude"`.

#### bot_discord.py

Discord slash command `/start` adds an optional `cli` choice parameter with values: `claude`, `codex`, `gemini`, `opencode`.

```
/start gpu-server ~/myproject              → cli_type="claude" (default)
/start gpu-server ~/myproject --cli gemini → cli_type="gemini"
/start gpu-server ~/myproject --gemini     → cli_type="gemini" (shorthand)
```

### Skill Sync

```rust
pub fn sync_to_project(&self, path: &Path, cli_type: &str) -> Result<()> {
    let adapter = create_adapter(cli_type);
    let instructions_file = adapter.instructions_file();
    // Sync instructions_file to project root
    if let Some(skills_dir) = adapter.skills_dir() {
        // Sync skills directory (currently only Claude)
    }
}
```

| CLI | Instructions File | Skills Dir |
|-----|-------------------|------------|
| Claude | `CLAUDE.md` | `.claude/skills/` |
| Codex | `AGENTS.md` | None |
| Gemini | `GEMINI.md` | None |
| OpenCode | `AGENTS.md` | None |

---

## Per-CLI Adapter Specifications

Each adapter below is **independent** and can be implemented in parallel after the shared infrastructure is in place.

---

### Adapter 1: ClaudeAdapter (Extract from Current Code)

**Status:** Existing code, needs extraction into adapter pattern.

#### Command Construction

```bash
# First message
claude --print "message" --output-format stream-json --verbose --include-partial-messages \
  --dangerously-skip-permissions    # mode=auto

# Resume
claude --print "message" --output-format stream-json --verbose --include-partial-messages \
  --resume <sdk_session_id> --dangerously-skip-permissions
```

#### Permission Mode Mapping

| Codecast Mode | Claude CLI Flags |
|---|---|
| `auto` | `--dangerously-skip-permissions` |
| `code` | acceptEdits |
| `plan` | read-only |
| `ask` | confirm everything |

#### Output Event Mapping

Existing `convert_claude_message()` logic moves to `ClaudeAdapter::parse_output_line()`. No behavior change — pure extraction.

| Claude Event Type | StreamEvent |
|---|---|
| `system` | `System { subtype, session_id, model }` |
| `assistant` | `Text` + `ToolUse` (multiple from one message) |
| `stream_event` → `content_block_delta` | `Partial { content }` |
| `stream_event` → `content_block_start` (tool_use) | `ToolUse { tool }` |
| `tool_progress` | `ToolUse { tool, message: status }` |
| `result` | `Result { session_id }` |
| `user` | (ignored) |

#### Session ID

Extracted from `system` event's `session_id` field.

#### Implementation Notes

- Stateless adapter — no interior mutability needed
- `stderr_log_level`: `Error`
- `instructions_file`: `"CLAUDE.md"`
- `skills_dir`: `Some(".claude/skills/")`

---

### Adapter 2: CodexAdapter

**Status:** New implementation.

#### Command Construction

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

#### Permission Mode Mapping

| Codecast Mode | Codex CLI Flags |
|---|---|
| `auto` | `--full-auto` |
| `code` | `--full-auto` |
| `plan` | `--sandbox read-only` |
| `ask` | `--sandbox read-only --approval-policy on-failure` |

Note: `auto` and `code` both map to `--full-auto` — Claude's `code` mode has no exact Codex equivalent.

**Important**: Flag names must be verified against `codex exec --help` before implementation.

#### Output Event Mapping

Codex uses a `thread > turn > item` event hierarchy.

| Codex Event | StreamEvent | Notes |
|---|---|---|
| `thread.started` | `System { subtype: "init" }` | Extract `thread_id` as session ID |
| `turn.started` | (ignored) | |
| `item.started` (agent_message) | (ignored) | Wait for updated |
| `item.updated` (agent_message) | `Partial { content }` | Incremental text delta (cumulative → delta) |
| `item.completed` (agent_message) | `Text { content }` | Complete text block |
| `item.started` (command_execution) | `ToolUse { tool: "bash" }` | Command start |
| `item.completed` (command_execution) | `ToolUse { tool: "bash", message }` | Command done with output |
| `item.started` (file_change) | `ToolUse { tool: "edit" }` | File edit start |
| `item.completed` (file_change) | `ToolUse { tool: "edit", message }` | Edit done |
| `item.*` (mcp_tool_call) | `ToolUse { tool: <name> }` | MCP tool call |
| `turn.completed` | `Result { session_id }` | Turn done |
| `turn.failed` | `Error { message }` | |
| `error` | `Error { message }` | Top-level error |

#### Incremental Text Handling

Codex `item.updated` events carry cumulative state, not pure deltas. `CodexAdapter` tracks the last seen text length via interior mutability (`Cell<usize>`) and emits only the new portion as `Partial { content }`.

#### Result Event and Thread ID

`CodexAdapter` captures `thread_id` from `thread.started` event (via `Cell<Option<String>>`) and emits it in the `Result` event when `turn.completed` arrives.

#### Tool Name Normalization

- `command_execution` → `bash`
- `file_change` → `edit`
- `mcp_tool_call` → actual tool name from event

#### Implementation Notes

- **Stateful** adapter — uses `Cell<usize>` for cumulative text delta, `Cell<Option<String>>` for thread_id
- `stderr_log_level`: `Info` (Codex sends progress to stderr)
- `instructions_file`: `"AGENTS.md"`
- `skills_dir`: `None`

---

### Adapter 3: GeminiAdapter

**Status:** New implementation.

#### Command Construction

```bash
# First message
gemini -p "message" --output-format stream-json --approval-mode yolo

# Resume session
gemini -p "message" --output-format stream-json --approval-mode yolo --resume <session_id>
```

Key differences from Claude CLI:
- Uses `-p` (not `--print`) for non-interactive prompt
- Uses `--output-format stream-json` (same flag name as Claude, but different event schema)
- Resume via `--resume` flag (supports UUID, index, or bare flag for latest)
- No `--input-format` — must kill/respawn per message (fits our per-message spawn model)
- No `--verbose` or `--include-partial-messages` equivalents

#### Permission Mode Mapping

| Codecast Mode | Gemini CLI Flags |
|---|---|
| `auto` | `--approval-mode yolo` |
| `code` | `--approval-mode auto_edit` |
| `plan` | `--sandbox` |
| `ask` | (default, no extra flags) |

Note: `--yolo` is deprecated in favor of `--approval-mode yolo`. Gemini's `auto_edit` is a closer match to Claude's `code` mode than Codex's `--full-auto`.

#### Output Event Mapping

Gemini uses flat event types with `type` field. Every event includes a `timestamp` field.

**Sample JSONL output** (from real Gemini CLI runs):

```jsonl
{"type":"init","timestamp":"2026-02-21T00:51:38.138Z","session_id":"70272ea8-4083-4590-ba02-242d377fa77b","model":"auto-gemini-3"}
{"type":"message","timestamp":"...","role":"user","content":"create a folder ./temp..."}
{"type":"message","timestamp":"...","role":"assistant","content":"I will create...","delta":true}
{"type":"tool_use","timestamp":"...","tool_name":"run_shell_command","tool_id":"run_shell_command_171635102963_0","parameters":{"command":"mkdir -p temp"}}
{"type":"tool_result","timestamp":"...","tool_id":"run_shell_command_171635102963_0","status":"success","output":""}
{"type":"result","timestamp":"...","status":"success","stats":{"total_tokens":1234,"input_tokens":800,"output_tokens":434,"tool_calls":1}}
```

| Gemini Event | StreamEvent | Notes |
|---|---|---|
| `init` | `System { subtype: "init", session_id, model }` | Contains `session_id` and `model` |
| `message` (role=user) | (ignored) | Echo of user input |
| `message` (role=assistant, delta=true) | `Partial { content }` | Streaming text chunk |
| `message` (role=assistant, delta absent/false) | `Text { content }` | Complete message (non-streaming) |
| `tool_use` | `ToolUse { tool: tool_name }` | Tool invocation with parameters |
| `tool_result` (status=success) | `ToolUse { tool: tool_id, message: output }` | Tool execution result |
| `tool_result` (status=error) | `Error { message: error.message }` | Tool failure |
| `error` | `Error { message }` | Non-fatal error |
| `result` (status=success) | `Result { session_id }` | Final outcome with stats |
| `result` (status=error) | `Error { message: error.message }` | Fatal error at turn end |

#### Incremental Text Handling

Gemini `message` events with `delta: true` are **pure deltas** (not cumulative), so **no cumulative tracking is needed** — unlike Codex. Each delta message's `content` field is the new text only. This is the simplest streaming model of all four CLIs.

#### Session ID

Extracted from `init` event's `session_id` field (UUID format). Stored via `Cell<Option<String>>` for inclusion in the final `Result` event.

#### Tool Name Normalization

Gemini uses descriptive tool names from its built-in tool set:
- `run_shell_command` → `bash`
- `write_file` / `replace` → `edit`
- `read_file` → `read`
- Other tool names → pass through as-is

#### Implementation Notes

- **Stateful** adapter — needs `Cell<Option<String>>` for session_id capture (from `init` → `Result`)
- `stderr_log_level`: `Info` (Gemini may send diagnostics to stderr)
- `instructions_file`: `"GEMINI.md"`
- `skills_dir`: `None`
- Gemini CLI requires Node.js on the remote machine (`npm install -g @google/gemini-cli`)

---

### Adapter 4: OpenCodeAdapter

**Status:** New implementation.

#### Command Construction

```bash
# First message
opencode run "message" --format json --quiet

# Resume session (continue last session)
opencode run "message" --format json --quiet --continue

# Resume specific session
opencode run "message" --format json --quiet --session <ses_id>
```

Key differences from Claude CLI:
- Uses `run` subcommand (not `--print`) for non-interactive mode
- JSON output via `--format json` (not `--output-format stream-json`)
- `--quiet` disables spinner (important for clean JSON parsing)
- Resume via `--session <id>` (not `--resume`)
- Session IDs are prefixed: `ses_<alphanumeric>`
- In non-interactive mode, all permissions are auto-approved by default

#### Permission Mode Mapping

| Codecast Mode | OpenCode CLI Flags |
|---|---|
| `auto` | `--yolo` (or default in non-interactive) |
| `code` | `--yolo` |
| `plan` | Need to set agent to `plan` (TODO: verify `--agent plan` flag) |
| `ask` | (default interactive behavior, but non-interactive auto-approves) |

Note: OpenCode's non-interactive mode (`opencode run`) auto-approves all actions. To get `plan` mode, we may need to use `--agent plan`. The permission granularity is richer than other CLIs (per-tool allow/ask/deny) but the non-interactive mode bypasses most of it.

**TODO**: Verify whether `opencode run --agent plan` restricts tool access in non-interactive mode.

#### Output Event Mapping

OpenCode uses a `step_start > message.part.updated > step_finish` pattern.

| OpenCode Event | StreamEvent | Notes |
|---|---|---|
| `step_start` | `System { subtype: "init" }` | Contains `sessionID`, `part.messageID` |
| `message.part.updated` (type=text/thinking) | `Partial { content }` | Streaming text delta |
| `message.part.updated` (type=tool, state=running) | `ToolUse { tool: name }` | Tool invocation |
| `message.part.updated` (type=tool, state=completed) | `ToolUse { tool: name, message }` | Tool result |
| `text` | `Text { content }` | Complete response text |
| `step_finish` | `Result { session_id }` | Turn done with token stats |
| Error events | `Error { message }` | |

#### Session ID

Extracted from `step_start` event's `sessionID` field. OpenCode session IDs follow the format `ses_<alphanumeric>`.

#### Tool Name Normalization

OpenCode uses Claude-compatible tool names (Read, Edit, Write, Bash, Glob, Grep, etc.):
- `Read` → `read`
- `Edit` / `Write` / `MultiEdit` → `edit`
- `Bash` → `bash`
- `Glob` / `Grep` → pass through lowercase
- `Task` → `subagent`
- Other names → pass through lowercase

#### Implementation Notes

- **Stateful** adapter — needs `Cell<Option<String>>` for session_id capture
- `stderr_log_level`: `Info`
- `instructions_file`: `"AGENTS.md"`
- `skills_dir`: `None`
- OpenCode is a Go binary — must be pre-installed on remote machine
- OpenCode has its own TUI; we only use the headless `run` subcommand
- **Known issue**: `--continue`/`--session` may have reliability issues across multiple `opencode run` invocations ([issue #11680](https://github.com/anomalyco/opencode/issues/11680)) — test thoroughly
- **Known issue**: `--command` flag breaks JSON output ([issue #2923](https://github.com/anomalyco/opencode/issues/2923)) — avoid `--command` in adapter

---

## Implementation Phases

### Phase 1: Shared Infrastructure (Sequential, blocks all adapters)

1. Create `cli_adapter/mod.rs` with trait + factory
2. Extract `ClaudeAdapter` from `session_pool.rs` + `types.rs`
3. Modify `session_pool.rs` to use adapter pattern
4. Modify `server.rs` to parse `cli_type`
5. Modify `skill_manager.rs` to use adapter
6. Head Node: `daemon_client.py`, `engine.py`, `session_router.py`, `bot_discord.py`, `message_formatter.py`
7. Tests for shared infrastructure

### Phase 2: Per-CLI Adapters (Parallel, independent)

After Phase 1 completes, these three tasks can run **in parallel** as they have zero dependencies on each other:

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ CodexAdapter │  │GeminiAdapter │  │OpenCodeAdapt │
│   codex.rs   │  │  gemini.rs   │  │ opencode.rs  │
│  + tests     │  │  + tests     │  │  + tests     │
└──────────────┘  └──────────────┘  └──────────────┘
```

Each adapter implementation includes:
- The adapter struct + trait impl (~100-200 lines)
- Unit tests with sample JSON output from the CLI
- Permission mode mapping tests
- Tool name normalization tests

---

## File Change Summary

### Shared (Phase 1)

| File | Change |
|---|---|
| `src/daemon/cli_adapter/mod.rs` | **New** — CliAdapter trait + factory |
| `src/daemon/cli_adapter/claude.rs` | **New** — Extract from session_pool.rs + types.rs |
| `src/daemon/session_pool.rs` | **Modify** — Use CliAdapter, add cli_type to InternalSession |
| `src/daemon/server.rs` | **Modify** — Parse cli_type in session.create |
| `src/daemon/types.rs` | **Modify** — Remove `convert_claude_message()`, remove `PermissionMode::to_cli_flags()`, add `cli_type` to `SessionInfo` |
| `src/daemon/skill_manager.rs` | **Modify** — Use instructions_file() + skills_dir() from adapter |
| `src/head/daemon_client.py` | **Modify** — create_session adds cli_type |
| `src/head/engine.py` | **Modify** — cmd_start parses --cli/shorthand flags, cmd_clear/cmd_new carry cli_type |
| `src/head/bot_discord.py` | **Modify** — Slash command adds cli choice |
| `src/head/session_router.py` | **Modify** — cli_type column + Session dataclass |
| `src/head/message_formatter.py` | **Modify** — /status and /ls show cli_type |

### Per-Adapter (Phase 2, parallel)

| File | Change |
|---|---|
| `src/daemon/cli_adapter/codex.rs` | **New** — CodexAdapter |
| `src/daemon/cli_adapter/gemini.rs` | **New** — GeminiAdapter |
| `src/daemon/cli_adapter/opencode.rs` | **New** — OpenCodeAdapter |

---

## Testing Strategy

### Shared Infrastructure Tests (Phase 1)

- `ClaudeAdapter` regression tests — identical behavior to current `convert_claude_message()`
- `create_adapter()` factory routing: each string maps to correct adapter
- `session_router` cli_type column migration and CRUD tests
- `daemon_client.create_session()` parameter passing tests
- `/start --cli <type>` argument parsing tests for all 4 CLI types
- `/status` and `/ls session` CLI type display tests

### Per-Adapter Tests (Phase 2, parallel)

Each adapter needs:
1. **Parse tests** — Sample JSON lines from the CLI → expected `Vec<StreamEvent>`
2. **Session ID extraction** — Correct field from init/start event
3. **Permission mode mapping** — All 4 Codecast modes → correct CLI flags
4. **Tool name normalization** — CLI-specific names → canonical names
5. **Command construction** — Correct binary, subcommands, flags for new + resume
6. **Cumulative text delta** (Codex only) — Verify delta computation from cumulative state

---

## Out of Scope

- **CLI-specific advanced features:**
  - Codex: `--image`, `--add-dir`, `--ephemeral`, `--output-schema`, `codex fork`
  - Gemini: `--extensions`, `--all-files`, checkpointing, `@<path>` file injection, sandbox profiles, policy engine
  - OpenCode: `--fork`, `--share`, `--command`, `opencode serve` server mode, ACP protocol, subagent invocation (`@general`)
- **Config-level API key management** — relies on remote machine's pre-configured environment
- **Skills directory sync for non-Claude CLIs** — only Claude has `.claude/skills/`
- **Multi-model selection within a CLI session**
- **Long-lived subprocess mode** — Claude's `--input-format stream-json`, OpenCode's ACP (`opencode acp`)
- **Conversation branching** — Gemini's `/chat save`+`/chat resume`, OpenCode's `--fork`
