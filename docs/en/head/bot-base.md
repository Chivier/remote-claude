# Bot Base (bot_base.py)

**File:** `head/bot_base.py`

Abstract base class for Discord and Telegram bot implementations. Contains all shared command handling logic, message forwarding, and streaming display.

## Purpose

- Define the abstract interface that platform-specific bots must implement
- Implement the command dispatcher routing `/commands` to handler methods
- Handle message forwarding to Claude sessions with real-time streaming display
- Manage concurrency (prevent simultaneous streaming to the same channel)

## Class: BotBase (ABC)

```python
class BotBase(ABC):
    ssh: SSHManager
    router: SessionRouter
    daemon: DaemonClient
    config: Config
    _streaming: set[str]  # Channels currently streaming
```

## Abstract Methods

Subclasses (DiscordBot, TelegramBot) must implement these:

| Method | Description |
|---|---|
| `send_message(channel_id, text) -> Any` | Send a new message to the channel. Returns a platform message object. |
| `edit_message(channel_id, message_obj, text) -> None` | Edit an existing message (for streaming updates). |
| `start() -> None` | Connect to the platform and begin listening. |
| `stop() -> None` | Disconnect from the platform. |

## Command Dispatcher

### `handle_input(channel_id: str, text: str) -> None`

Main entry point for all user input. If the text starts with `/`, routes to the command dispatcher. Otherwise, forwards to the active Claude session.

### `_handle_command(channel_id: str, text: str) -> None`

Parses the command and dispatches to the appropriate handler:

| Command | Aliases | Handler |
|---|---|---|
| `/start` | | `cmd_start` |
| `/resume` | | `cmd_resume` |
| `/ls` | `/list` | `cmd_ls` |
| `/exit` | | `cmd_exit` |
| `/rm` | `/remove`, `/destroy` | `cmd_rm` |
| `/mode` | | `cmd_mode` |
| `/status` | | `cmd_status` |
| `/interrupt` | | `cmd_interrupt` |
| `/health` | | `cmd_health` |
| `/monitor` | | `cmd_monitor` |
| `/help` | | `cmd_help` |

All commands are wrapped in error handling that catches `DaemonConnectionError`, `DaemonError`, and generic exceptions, formatting them as error messages to the user.

## Command Implementations

### `cmd_start(channel_id, args, silent_init=False)`

Creates a new session: `/start <machine_id> <path>`

1. Validates that two arguments are provided
2. Establishes SSH tunnel via `ssh.ensure_tunnel()`
3. Syncs skills via `ssh.sync_skills()`
4. Creates a daemon session via `daemon.create_session()`
5. Registers the session in the router
6. Sends confirmation with session ID and mode

The `silent_init` parameter suppresses the initial "Starting session..." message (used by Discord slash commands which have their own initial response).

### `cmd_resume(channel_id, args)`

Resumes a session: `/resume <session_id>`

1. Looks up the session by daemon ID in the router (checks both active and logged sessions)
2. Ensures the SSH tunnel
3. Calls `daemon.resume_session()` with the SDK session ID if available
4. Re-registers the session as active

### `cmd_ls(channel_id, args)`

Lists machines or sessions: `/ls machine` or `/ls session [machine]`

### `cmd_exit(channel_id)`

Detaches from the current session without destroying it. The session can be resumed later.

### `cmd_rm(channel_id, args)`

Destroys sessions: `/rm <machine_id> <path>`

Finds all sessions matching the machine/path combination and destroys them both on the daemon and in the local router.

### `cmd_mode(channel_id, args)`

Changes the permission mode: `/mode <auto|code|plan|ask>`

Accepts both internal names (`auto`) and display names (`bypass`). Updates both the daemon and the local session state.

### `cmd_status(channel_id)`

Shows the current session status including queue statistics.

### `cmd_interrupt(channel_id)`

Interrupts Claude's current operation by sending SIGTERM to the running CLI process.

### `cmd_health(channel_id, args)`

Checks daemon health. If no machine is specified, checks the current session's machine or all connected machines.

### `cmd_monitor(channel_id, args)`

Shows detailed monitoring information for sessions on a machine.

### `cmd_help(channel_id)`

Displays the help message listing all available commands.

## Message Forwarding

### `_forward_message(channel_id: str, text: str) -> None`

Forwards a user message to the active Claude session and streams the response back.

**Concurrency control:** The `_streaming` set tracks which channels currently have an active stream. If a channel is already streaming, the user gets a "Claude is still processing" message.

**Streaming display flow:**

1. Resolve session from the router
2. Ensure SSH tunnel
3. Call `daemon.send_message()` which returns an async iterator of events
4. For each event:
   - `partial`: Accumulate text in a buffer. Periodically (every 1.5 seconds) send or edit a message with the buffer content plus a cursor indicator (`▌`). If the buffer exceeds 1800 characters, finalize the current message and start a new one.
   - `text`: Complete text block. If a streaming message exists, edit it with the final content. Otherwise, send as new message(s) (split if needed).
   - `tool_use`: Format and send as a new message showing the tool name and input.
   - `result`: Capture the SDK session ID for future `--resume` calls.
   - `system` (init): Display the connected model and current mode.
   - `queued`: Notify the user their message is queued with its position.
   - `error`: Display the error message.
   - `ping`: Ignored (keepalive from daemon).
5. After the stream ends, flush any remaining buffer content.

## Constants

| Constant | Value | Description |
|---|---|---|
| `STREAM_UPDATE_INTERVAL` | 1.5 seconds | How often to update the streaming message |
| `STREAM_BUFFER_FLUSH_SIZE` | 1800 chars | Force a new message when buffer exceeds this |

## Connection to Other Modules

- **bot_discord.py** and **bot_telegram.py** extend this class
- Uses **SSHManager** for tunnel management and skills sync
- Uses **SessionRouter** for session state
- Uses **DaemonClient** for all daemon communication
- Uses **message_formatter** for output formatting
