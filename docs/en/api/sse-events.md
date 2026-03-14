# SSE Stream Events

When the Head Node sends a `session.send` RPC call, the daemon responds with a Server-Sent Events (SSE) stream. This document describes all event types that can appear in the stream.

## SSE Format

Events are sent as `data:` lines with JSON payloads, separated by double newlines:

```
data: {"type":"partial","content":"Hello"}

data: {"type":"text","content":"Hello, world!"}

data: [DONE]
```

The stream ends with `data: [DONE]` (not a JSON payload).

## Event Types

### `system`

System events provide metadata about the session. The most common is the `init` subtype, sent when Claude starts processing.

```json
{
    "type": "system",
    "subtype": "init",
    "session_id": "sdk-session-uuid",
    "model": "claude-sonnet-4-20250514"
}
```

| Field | Type | Description |
|---|---|---|
| `subtype` | string | Event subtype (e.g., `init`) |
| `session_id` | string | Claude SDK session ID |
| `model` | string | Model name reported by Claude CLI |
| `raw` | object | Raw Claude CLI JSON message (optional) |

The Head Node uses the `init` event to display a "Connected to **model** | Mode: **mode**" message on the first interaction.

---

### `partial`

Streaming text deltas. These arrive as Claude generates text, providing real-time character-by-character output.

```json
{
    "type": "partial",
    "content": "Let me "
}
```

| Field | Type | Description |
|---|---|---|
| `content` | string | Text delta (may be a few characters or a word) |

The Head Node accumulates these deltas in a buffer and periodically updates the chat message with the current buffer content plus a cursor indicator (`▌`).

Partial events can also contain `partial_json` content from tool use streaming, which is rendered the same way.

---

### `text`

A complete text block from Claude. This represents a finished text content block in Claude's response.

```json
{
    "type": "text",
    "content": "Here is the complete analysis of your project...",
    "raw": { ... }
}
```

| Field | Type | Description |
|---|---|---|
| `content` | string | Complete text content |
| `raw` | object | Raw Claude CLI message (optional) |

If partial events were being streamed, the `text` event replaces the accumulated partial content. If no partials were sent, the text is sent as a new message.

---

### `tool_use`

Indicates Claude is invoking a tool (file write, bash command, etc.).

```json
{
    "type": "tool_use",
    "tool": "Write",
    "input": {
        "file_path": "/home/user/project/README.md",
        "content": "# My Project\n..."
    },
    "raw": { ... }
}
```

or with a status message (from `tool_progress`):

```json
{
    "type": "tool_use",
    "tool": "Bash",
    "message": "Running command...",
    "raw": { ... }
}
```

| Field | Type | Description |
|---|---|---|
| `tool` | string | Tool name (e.g., `Write`, `Bash`, `Read`, `Glob`, `Grep`) |
| `input` | object | Tool input parameters (optional) |
| `message` | string | Tool progress status message (optional) |
| `raw` | object | Raw Claude CLI message (optional) |

The Head Node displays tool use as: `**[Tool: Write]** Creating file...` or with input in a code block.

---

### `result`

Indicates Claude has finished processing the message. Contains the SDK session ID needed for conversation continuity.

```json
{
    "type": "result",
    "session_id": "sdk-session-uuid-here",
    "raw": { ... }
}
```

| Field | Type | Description |
|---|---|---|
| `session_id` | string | Claude SDK session ID for `--resume` |
| `raw` | object | Raw result including `duration_ms` and `usage` (optional) |

The Head Node captures `session_id` and stores it in the SessionRouter for future `--resume` calls.

This is a **terminal event** -- the generator stops yielding after a `result`.

---

### `queued`

Sent when Claude is busy processing another message and the new message has been queued.

```json
{
    "type": "queued",
    "position": 2
}
```

| Field | Type | Description |
|---|---|---|
| `position` | number | Position in the queue (1-based) |

The Head Node displays: "Message queued (position: 2). Claude is busy with a previous request."

When the queued message is eventually processed, its events will flow through a subsequent `session.send` SSE stream (or be buffered if the client is disconnected).

---

### `error`

An error occurred during processing.

```json
{
    "type": "error",
    "message": "Claude process exited abnormally (code=1, signal=null)"
}
```

| Field | Type | Description |
|---|---|---|
| `message` | string | Human-readable error description |

Common error sources:
- Claude CLI process exiting with non-zero code
- Claude CLI process spawn failure
- Stream idle timeout (no events for 5 minutes)
- SSH connection loss

This is a **terminal event** -- the generator stops yielding after an `error`.

---

### `ping`

Keepalive event sent every 30 seconds to prevent idle SSH tunnel timeouts.

```json
{
    "type": "ping"
}
```

The Head Node ignores these events. They are purely to keep the HTTP connection alive through proxies and SSH tunnels that might close idle connections.

---

### `interrupted`

Sent when Claude's operation was interrupted (via `session.interrupt` or SIGTERM).

```json
{
    "type": "interrupted"
}
```

This is a **terminal event** -- the generator stops yielding after an `interrupted`.

---

## Event Flow Examples

### Simple Text Response

```
data: {"type":"system","subtype":"init","model":"claude-sonnet-4-20250514","session_id":"sdk-123"}
data: {"type":"partial","content":"The "}
data: {"type":"partial","content":"answer "}
data: {"type":"partial","content":"is 42."}
data: {"type":"text","content":"The answer is 42."}
data: {"type":"result","session_id":"sdk-123"}
data: [DONE]
```

### Tool Use with Text

```
data: {"type":"system","subtype":"init","model":"claude-sonnet-4-20250514"}
data: {"type":"partial","content":"Let me check..."}
data: {"type":"tool_use","tool":"Bash","input":{"command":"ls -la"}}
data: {"type":"tool_use","tool":"Bash","message":"Running command..."}
data: {"type":"partial","content":"Here are the files:\n"}
data: {"type":"partial","content":"- src/\n- package.json"}
data: {"type":"text","content":"Here are the files:\n- src/\n- package.json"}
data: {"type":"result","session_id":"sdk-456"}
data: [DONE]
```

### Queued Message

```
data: {"type":"queued","position":1}
data: [DONE]
```

### Error During Processing

```
data: {"type":"system","subtype":"init","model":"claude-sonnet-4-20250514"}
data: {"type":"partial","content":"Let me "}
data: {"type":"error","message":"Claude process exited abnormally (code=1, signal=null)"}
data: [DONE]
```

### Keepalive During Long Operation

```
data: {"type":"system","subtype":"init","model":"claude-sonnet-4-20250514"}
data: {"type":"partial","content":"Analyzing..."}
data: {"type":"ping"}
data: {"type":"partial","content":" the codebase structure"}
data: {"type":"ping"}
data: {"type":"tool_use","tool":"Glob","input":{"pattern":"**/*.ts"}}
data: {"type":"text","content":"I found 15 TypeScript files..."}
data: {"type":"result","session_id":"sdk-789"}
data: [DONE]
```
