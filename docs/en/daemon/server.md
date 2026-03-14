# RPC Server (server.ts)

**File:** `daemon/src/server.ts`

Express-based JSON-RPC server that provides the HTTP endpoint for all daemon operations. Handles method routing, SSE streaming, keepalive pings, and graceful shutdown.

## Purpose

- Provide a single `POST /rpc` endpoint for all JSON-RPC methods
- Route requests to the appropriate handler based on the `method` field
- Stream responses for `session.send` via SSE (Server-Sent Events)
- Send keepalive pings to prevent idle timeouts
- Handle graceful shutdown on SIGTERM/SIGINT

## Server Configuration

```typescript
const PORT = parseInt(process.env.DAEMON_PORT || "9100", 10);
const HOST = "127.0.0.1"; // Only accessible via SSH tunnel
```

The server binds to localhost only. The port is configurable via the `DAEMON_PORT` environment variable.

## Components

The server creates two singleton instances at startup:

```typescript
const sessionPool = new SessionPool();
const skillManager = new SkillManager();
```

It also records `startTime` for uptime calculations in health checks.

## Method Routing

All requests come through `POST /rpc`. The `method` field in the request body determines which handler is invoked:

| Method | Handler | Response Type |
|---|---|---|
| `session.create` | `handleCreateSession` | JSON |
| `session.send` | `handleSendMessage` | SSE stream |
| `session.resume` | `handleResumeSession` | JSON |
| `session.destroy` | `handleDestroySession` | JSON |
| `session.list` | `handleListSessions` | JSON |
| `session.set_mode` | `handleSetMode` | JSON |
| `session.interrupt` | `handleInterruptSession` | JSON |
| `session.queue_stats` | `handleQueueStats` | JSON |
| `session.reconnect` | `handleReconnect` | JSON |
| `health.check` | `handleHealthCheck` | JSON |
| `monitor.sessions` | `handleMonitorSessions` | JSON |

Unknown methods return error code `-32601` (Method not found).

## SSE Streaming (session.send)

The `handleSendMessage` handler is unique -- it responds with an SSE stream instead of a JSON body:

```typescript
res.setHeader("Content-Type", "text/event-stream");
res.setHeader("Cache-Control", "no-cache");
res.setHeader("Connection", "keep-alive");
res.setHeader("X-Accel-Buffering", "no"); // Disable nginx buffering
```

### Client Disconnect Handling

The server listens for the `close` event on the response to detect client disconnection:

```typescript
res.on("close", () => {
    clientDisconnected = true;
    sessionPool.clientDisconnect(params.sessionId);
});
```

If the client disconnects mid-stream, remaining events are buffered via `sessionPool.bufferEvent()` for later retrieval with `session.reconnect`.

### Keepalive Pings

A keepalive interval sends a `ping` event every 30 seconds to prevent idle SSH tunnel timeouts:

```typescript
const keepaliveInterval = setInterval(() => {
    res.write(`data: ${JSON.stringify({ type: "ping" })}\n\n`);
}, 30000);
```

### Stream Termination

The stream ends with `data: [DONE]\n\n` when all events have been sent. If an error occurs, an error event is sent before `[DONE]`.

## Method Handlers

### `handleCreateSession`

1. Validates the `path` parameter
2. Syncs skills to the project directory via `skillManager.syncToProject()`
3. Creates a session in the pool (lightweight -- no process spawned)
4. Returns `{ sessionId }`

### `handleSendMessage`

See SSE Streaming section above.

### `handleResumeSession`

Delegates to `sessionPool.resume()`. Returns `{ ok, fallback }`.

### `handleDestroySession`

Delegates to `sessionPool.destroy()`. Returns `{ ok }`.

### `handleListSessions`

Returns `{ sessions: [...] }` with all session info.

### `handleSetMode`

Delegates to `sessionPool.setMode()`. Returns `{ ok }`.

### `handleInterruptSession`

Delegates to `sessionPool.interrupt()`. Returns `{ ok, interrupted }`.

### `handleQueueStats`

Returns queue statistics for a specific session: `{ userPending, responsePending, clientConnected }`.

### `handleReconnect`

Calls `sessionPool.clientReconnect()` to mark the client as reconnected and retrieve buffered events. Returns `{ bufferedEvents: [...] }`.

### `handleHealthCheck`

Returns daemon health information:

```json
{
    "ok": true,
    "sessions": 3,
    "sessionsByStatus": { "idle": 2, "busy": 1 },
    "uptime": 3600,
    "memory": { "rss": 45, "heapUsed": 20, "heapTotal": 30 },
    "nodeVersion": "v20.11.0",
    "pid": 12345
}
```

Memory values are in megabytes.

### `handleMonitorSessions`

Returns detailed session information including queue stats for each session.

## JSON-RPC Helpers

```typescript
function rpcSuccess(result: unknown, id?: string): RpcResponse
function rpcError(code: number, message: string, id?: string): RpcResponse
```

Standard error codes used:
- `-32600`: Invalid request (missing method)
- `-32601`: Method not found
- `-32602`: Invalid params (missing required params)
- `-32000`: Internal/application error

## Graceful Shutdown

```typescript
process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
```

The `shutdown()` function calls `sessionPool.destroyAll()` to kill all running Claude processes and clean up, then exits the process.

## Connection to Other Modules

- Uses **SessionPool** for all session lifecycle operations
- Uses **SkillManager** for skills sync on session creation
- Imports types from **types.ts** for request/response typing
