# Message Formatter (message_formatter.py)

**File:** `head/message_formatter.py`

Handles message splitting for platform character limits and formatting of various output types for display in Discord and Telegram.

## Purpose

- Split long messages into chunks that respect platform limits (Discord: 2000, Telegram: 4096)
- Smart splitting that avoids breaking code blocks and prefers natural boundaries
- Format tool use events, machine lists, session lists, status reports, health checks, and monitoring data
- Map internal mode names to user-facing display names

## Mode Display Names

Internal mode names are mapped to user-facing names:

| Internal | Display |
|---|---|
| `auto` | `bypass` |
| `code` | `code` |
| `plan` | `plan` |
| `ask` | `ask` |

The `auto` mode is displayed as `bypass` to make it clear that permissions are bypassed entirely.

```python
def display_mode(mode: str) -> str
```

## Message Splitting

### `split_message(text: str, max_len: int = 2000) -> list[str]`

Splits a long message into chunks that fit within the platform's character limit.

**Splitting priority (in order):**

1. **Code block awareness**: If a split would occur inside a code block (odd number of `` ``` `` markers), the split point is moved to before the code block starts.
2. **Paragraph boundary** (`\n\n`): Preferred split point, must be at least 30% into the text.
3. **Line boundary** (`\n`): Next best option, also requires 30% minimum position.
4. **Sentence boundary** (`. `, `! `, `? `, `; `): Requires 50% minimum position.
5. **Word boundary** (space): Requires 50% minimum position.
6. **Forced split**: At exactly `max_len` if no natural boundary is found.

Empty chunks are filtered out of the result.

## Formatting Functions

### `format_tool_use(event: dict) -> str`

Formats a `tool_use` event for chat display.

```
**[Tool: Write]** Creating file at /path/to/file
```

or with input data:

```
**[Tool: Bash]**
\`\`\`
{"command": "ls -la"}
\`\`\`
```

Input data is truncated to 500 characters.

### `format_machine_list(machines: list[dict]) -> str`

Formats the machine list for `/ls machine`:

```
**Machines:**
🟢 **gpu-1** (gpu1.example.com) ⚡
  Paths: `/home/user/project-a`, `/home/user/project-b`
🔴 **gpu-2** (gpu2.lab.internal) 💤
```

Icons:
- 🟢 online / 🔴 offline
- ⚡ daemon running / 💤 daemon stopped

### `format_session_list(sessions: list) -> str`

Formats the session list for `/ls session`:

```
**Sessions:**
● `a1b2c3d4...` **gpu-1**:`/home/user/project` [bypass] (active)
○ `e5f6g7h8...` **gpu-1**:`/home/user/other` [code] (detached)
```

Status icons: ● active, ○ detached, ✕ destroyed, ◉ busy

### `format_session_info(session) -> str`

Formats a single session for display. Handles both `Session` objects (from SessionRouter) and dict objects (from daemon API).

### `format_error(error: str) -> str`

Formats an error message:

```
**Error:** message text
```

### `format_status(session, queue_stats=None) -> str`

Formats the `/status` output:

```
**Session Status**
Machine: **gpu-1**
Path: `/home/user/project`
Mode: **bypass**
Status: **active**
Session ID: `a1b2c3d4e5f6...`
SDK Session: `x9y8z7w6v5u4...`
Queue: 0 pending messages
Buffered: 0 responses
```

### `format_health(machine_id, health) -> str`

Formats the `/health` output:

```
**Daemon Health - gpu-1**
Status: OK
Uptime: 2h15m30s
Sessions: 3 (idle: 2, busy: 1)
Memory: 45MB RSS, 20/30MB heap
Node: v20.11.0 (PID: 12345)
```

Uptime is formatted as hours/minutes/seconds.

### `format_monitor(machine_id, monitor) -> str`

Formats the `/monitor` output with detailed per-session information:

```
**Monitor - gpu-1** (uptime: 2h15m30s, 2 session(s))

● `a1b2c3d4...` **idle** [bypass | claude-sonnet-4-20250514]
  Path: `/home/user/project`
  Client: connected | Queue: 0 pending, 0 buffered

◉ `e5f6g7h8...` **busy** [code | claude-sonnet-4-20250514]
  Path: `/home/user/other`
  Client: **disconnected** | Queue: 1 pending, 5 buffered
```

## Connection to Other Modules

- **bot_base.py** imports `split_message`, `format_tool_use`, `format_machine_list`, `format_session_list`, `format_error`, `format_status`, `format_health`, `format_monitor`, and `display_mode`
- **bot_discord.py** imports `split_message`, `format_error`, and `display_mode`
- **bot_telegram.py** imports `split_message`
