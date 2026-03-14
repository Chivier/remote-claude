# Session Router (session_router.py)

**File:** `head/session_router.py`

Manages session state in a local SQLite database. Maps bot channels (Discord or Telegram) to active Claude sessions on remote machines.

## Purpose

- Maintain a persistent registry of sessions across Head Node restarts
- Map chat channels to remote Claude sessions
- Track session lifecycle: active -> detached -> destroyed
- Log session history for resume capabilities
- Provide query methods for session lookup by channel, daemon ID, or machine/path

## Database Schema

### `sessions` table

Stores the current state of each session. Primary key is `channel_id` (one active session per channel).

| Column | Type | Description |
|---|---|---|
| `channel_id` | TEXT (PK) | Bot-specific channel ID (e.g., `discord:12345` or `telegram:67890`) |
| `machine_id` | TEXT | Remote machine identifier |
| `path` | TEXT | Project path on the remote machine |
| `daemon_session_id` | TEXT | UUID assigned by the daemon |
| `sdk_session_id` | TEXT | Claude SDK session ID (for `--resume`) |
| `status` | TEXT | `active`, `detached`, or `destroyed` |
| `mode` | TEXT | Permission mode (`auto`, `code`, `plan`, `ask`) |
| `created_at` | TEXT | ISO 8601 timestamp |
| `updated_at` | TEXT | ISO 8601 timestamp |

### `session_log` table

Append-only log of detached sessions. Used for session resume lookups.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER (PK) | Auto-increment ID |
| `channel_id` | TEXT | Original channel |
| `machine_id` | TEXT | Machine the session ran on |
| `path` | TEXT | Project path |
| `daemon_session_id` | TEXT | Daemon session UUID |
| `sdk_session_id` | TEXT | Claude SDK session ID |
| `mode` | TEXT | Permission mode at detach time |
| `created_at` | TEXT | When the session was created |
| `detached_at` | TEXT | When the session was detached |

Indexed on `machine_id` and `daemon_session_id` for fast lookups.

## Session Dataclass

```python
@dataclass
class Session:
    channel_id: str           # e.g., "discord:123456"
    machine_id: str           # e.g., "gpu-1"
    path: str                 # e.g., "/home/user/project"
    daemon_session_id: str    # UUID from daemon
    sdk_session_id: Optional[str]  # Claude SDK session ID
    status: str               # "active" | "detached" | "destroyed"
    mode: str                 # "auto" | "code" | "plan" | "ask"
    created_at: str           # ISO 8601
    updated_at: str           # ISO 8601
```

## Key Methods

### `resolve(channel_id: str) -> Optional[Session]`

Find the active session for a channel. Returns `None` if no active session exists. This is the primary lookup used when forwarding user messages to Claude.

### `register(channel_id, machine_id, path, daemon_session_id, mode) -> None`

Register a new active session for a channel. If an active session already exists on this channel, it is automatically detached first (moved to the session log). The new session is inserted with status `active`.

### `update_sdk_session(channel_id: str, sdk_session_id: str) -> None`

Update the SDK session ID for an active session. Called when a `result` event is received from Claude, which contains the session ID needed for future `--resume` calls.

### `update_mode(channel_id: str, mode: str) -> None`

Update the permission mode for the active session on a channel. Called when the user changes mode with `/mode`.

### `detach(channel_id: str) -> Optional[Session]`

Detach the active session on a channel without destroying it. The session is:

1. Copied to `session_log` with the current timestamp as `detached_at`
2. Status is updated to `detached` in the `sessions` table

Returns the detached session, or `None` if no active session was found. Detached sessions can be resumed later with `/resume`.

### `destroy(channel_id: str) -> Optional[Session]`

Mark a session as `destroyed`. Unlike detach, this does not log the session. Returns the destroyed session or `None`.

### `list_sessions(machine_id: Optional[str]) -> list[Session]`

List all sessions, optionally filtered by machine ID. Returns sessions ordered by `updated_at` descending (most recent first). Includes sessions in all statuses.

### `list_active_sessions() -> list[Session]`

List only sessions with status `active`.

### `find_session_by_daemon_id(daemon_session_id: str) -> Optional[Session]`

Find a session by its daemon-assigned UUID. Searches both the active `sessions` table and the `session_log` table. Used by `/resume` to locate previously detached sessions.

### `find_sessions_by_machine_path(machine_id: str, path: str) -> list[Session]`

Find all sessions on a specific machine and path. Used by `/rm` to destroy sessions matching a machine/path combination.

## Connection to Other Modules

- **main.py** creates the SessionRouter with the database path
- **BotBase** calls `resolve()` before every message forward, `register()` on `/start`, `detach()` on `/exit`, `destroy()` via `/rm`, and query methods for `/ls`, `/resume`, `/status`
- **BotBase** calls `update_sdk_session()` when a `result` event provides the Claude SDK session ID
- **BotBase** calls `update_mode()` when the user changes the permission mode
