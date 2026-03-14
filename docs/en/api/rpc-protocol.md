# JSON-RPC Protocol

The daemon exposes a single HTTP endpoint at `POST /rpc` that accepts JSON-RPC requests. All communication between the Head Node and the daemon uses this protocol.

## Endpoint

```
POST http://127.0.0.1:{port}/rpc
Content-Type: application/json
```

The daemon only binds to `127.0.0.1`. Access is through SSH port forwarding managed by the Head Node.

## Request Format

```json
{
    "method": "session.create",
    "params": { "path": "/home/user/project", "mode": "auto" },
    "id": "optional-request-id"
}
```

## Response Format

**Success:**

```json
{
    "result": { "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890" },
    "id": "optional-request-id"
}
```

**Error:**

```json
{
    "error": { "code": -32602, "message": "Missing required param: path" },
    "id": "optional-request-id"
}
```

## Error Codes

| Code | Meaning |
|---|---|
| `-32600` | Invalid request (missing method) |
| `-32601` | Method not found |
| `-32602` | Invalid params (missing required parameters) |
| `-32000` | Internal/application error (session not found, etc.) |

---

## Methods

### `session.create`

Create a new Claude session. This is lightweight -- no Claude process is spawned until a message is sent.

**Request:**

```json
{
    "method": "session.create",
    "params": {
        "path": "/home/user/project",
        "mode": "auto"
    }
}
```

| Param | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | Absolute path to the project directory on the remote machine. Must exist. |
| `mode` | string | no | Permission mode: `auto`, `code`, `plan`, `ask`. Defaults to `auto`. |

**Response:**

```json
{
    "result": {
        "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    }
}
```

**Side effects:**
- Skills are synced to the project directory before the session is created
- The path is validated to exist on the filesystem

---

### `session.send`

Send a message to a Claude session. Unlike other methods, this returns an **SSE stream** instead of a JSON response.

**Request:**

```json
{
    "method": "session.send",
    "params": {
        "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "message": "What files are in this project?"
    }
}
```

| Param | Type | Required | Description |
|---|---|---|---|
| `sessionId` | string | yes | Session UUID from `session.create`. |
| `message` | string | yes | The user's message to send to Claude. |

**Response:** SSE stream (Content-Type: `text/event-stream`)

```
data: {"type":"system","subtype":"init","model":"claude-sonnet-4-20250514"}

data: {"type":"partial","content":"Let me "}

data: {"type":"partial","content":"look at "}

data: {"type":"partial","content":"the files..."}

data: {"type":"tool_use","tool":"Bash","input":{"command":"ls -la"}}

data: {"type":"text","content":"Here are the files in this project:\n\n- src/\n- package.json\n- README.md"}

data: {"type":"result","session_id":"sdk-session-uuid-here"}

data: [DONE]
```

If Claude is busy processing another message:

```
data: {"type":"queued","position":1}

data: [DONE]
```

See [SSE Stream Events](./sse-events.md) for full event type documentation.

**Side effects:**
- Spawns a `claude --print` process for the duration of the message
- Captures the SDK session ID from the result for future `--resume`
- After completion, auto-processes the next queued message if any

---

### `session.resume`

Resume a previously detached session. Updates the SDK session ID so the next `send()` uses `--resume`.

**Request:**

```json
{
    "method": "session.resume",
    "params": {
        "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "sdkSessionId": "sdk-session-uuid-here"
    }
}
```

| Param | Type | Required | Description |
|---|---|---|---|
| `sessionId` | string | yes | Daemon session UUID. |
| `sdkSessionId` | string | no | Claude SDK session ID for `--resume`. |

**Response:**

```json
{
    "result": {
        "ok": true,
        "fallback": false
    }
}
```

| Field | Type | Description |
|---|---|---|
| `ok` | boolean | Whether the session was found and resumed |
| `fallback` | boolean | Whether a fresh session was created (with history injected) instead of true resume |

---

### `session.destroy`

Destroy a session and kill any running Claude process.

**Request:**

```json
{
    "method": "session.destroy",
    "params": {
        "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    }
}
```

| Param | Type | Required | Description |
|---|---|---|---|
| `sessionId` | string | yes | Session UUID to destroy. |

**Response:**

```json
{
    "result": {
        "ok": true
    }
}
```

**Side effects:**
- Sends SIGTERM to any running Claude process (SIGKILL after 5 seconds)
- Clears message queues
- Removes the session from the pool

---

### `session.list`

List all sessions on the daemon.

**Request:**

```json
{
    "method": "session.list",
    "params": {}
}
```

No parameters required.

**Response:**

```json
{
    "result": {
        "sessions": [
            {
                "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "path": "/home/user/project",
                "status": "idle",
                "mode": "auto",
                "sdkSessionId": "sdk-uuid",
                "model": "claude-sonnet-4-20250514",
                "createdAt": "2026-03-14T10:00:00.000Z",
                "lastActivityAt": "2026-03-14T10:05:00.000Z"
            }
        ]
    }
}
```

---

### `session.set_mode`

Change the permission mode for a session. Takes effect on the next message.

**Request:**

```json
{
    "method": "session.set_mode",
    "params": {
        "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "mode": "code"
    }
}
```

| Param | Type | Required | Description |
|---|---|---|---|
| `sessionId` | string | yes | Session UUID. |
| `mode` | string | yes | New mode: `auto`, `code`, `plan`, `ask`. |

**Response:**

```json
{
    "result": {
        "ok": true
    }
}
```

---

### `session.interrupt`

Interrupt Claude's current operation. Sends SIGTERM to the running Claude CLI process.

**Request:**

```json
{
    "method": "session.interrupt",
    "params": {
        "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    }
}
```

| Param | Type | Required | Description |
|---|---|---|---|
| `sessionId` | string | yes | Session UUID. |

**Response:**

```json
{
    "result": {
        "ok": true,
        "interrupted": true
    }
}
```

| Field | Type | Description |
|---|---|---|
| `ok` | boolean | Always `true` if session exists |
| `interrupted` | boolean | `true` if there was an active operation to interrupt, `false` if Claude was idle |

**Side effects:**
- Sends SIGTERM to the Claude CLI process
- Clears the message queue

---

### `session.queue_stats`

Get message queue statistics for a session.

**Request:**

```json
{
    "method": "session.queue_stats",
    "params": {
        "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    }
}
```

| Param | Type | Required | Description |
|---|---|---|---|
| `sessionId` | string | yes | Session UUID. |

**Response:**

```json
{
    "result": {
        "userPending": 2,
        "responsePending": 0,
        "clientConnected": true
    }
}
```

| Field | Type | Description |
|---|---|---|
| `userPending` | number | Number of user messages waiting to be processed |
| `responsePending` | number | Number of response events buffered (for SSH reconnect) |
| `clientConnected` | boolean | Whether the Head Node client is currently connected |

---

### `session.reconnect`

Reconnect to a session and retrieve any buffered response events.

**Request:**

```json
{
    "method": "session.reconnect",
    "params": {
        "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    }
}
```

| Param | Type | Required | Description |
|---|---|---|---|
| `sessionId` | string | yes | Session UUID. |

**Response:**

```json
{
    "result": {
        "bufferedEvents": [
            {"type": "partial", "content": "Here is "},
            {"type": "text", "content": "Here is the answer to your question."},
            {"type": "result", "session_id": "sdk-uuid"}
        ]
    }
}
```

**Side effects:**
- Marks the client as reconnected
- Clears the response buffer after replay

---

### `health.check`

Check daemon health and system information.

**Request:**

```json
{
    "method": "health.check",
    "params": {}
}
```

No parameters required.

**Response:**

```json
{
    "result": {
        "ok": true,
        "sessions": 3,
        "sessionsByStatus": {
            "idle": 2,
            "busy": 1
        },
        "uptime": 3600,
        "memory": {
            "rss": 45,
            "heapUsed": 20,
            "heapTotal": 30
        },
        "nodeVersion": "v20.11.0",
        "pid": 12345
    }
}
```

| Field | Type | Description |
|---|---|---|
| `ok` | boolean | Always `true` when the daemon is responding |
| `sessions` | number | Total number of sessions |
| `sessionsByStatus` | object | Count of sessions per status (idle, busy, error, destroyed) |
| `uptime` | number | Daemon uptime in seconds |
| `memory.rss` | number | Resident Set Size in MB |
| `memory.heapUsed` | number | V8 heap used in MB |
| `memory.heapTotal` | number | V8 total heap in MB |
| `nodeVersion` | string | Node.js version string |
| `pid` | number | Daemon process ID |

---

### `monitor.sessions`

Get detailed monitoring information for all sessions, including queue stats.

**Request:**

```json
{
    "method": "monitor.sessions",
    "params": {}
}
```

No parameters required.

**Response:**

```json
{
    "result": {
        "sessions": [
            {
                "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "path": "/home/user/project",
                "status": "busy",
                "mode": "auto",
                "model": "claude-sonnet-4-20250514",
                "sdkSessionId": "sdk-uuid",
                "createdAt": "2026-03-14T10:00:00.000Z",
                "lastActivityAt": "2026-03-14T10:05:00.000Z",
                "queue": {
                    "userPending": 1,
                    "responsePending": 0,
                    "clientConnected": true
                }
            }
        ],
        "totalSessions": 1,
        "uptime": 3600
    }
}
```
