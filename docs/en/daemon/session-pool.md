# Session Pool (session-pool.ts)

**File:** `daemon/src/session-pool.ts`

Manages Claude CLI sessions using a per-message spawn architecture. Each user message spawns a fresh `claude --print` process, maintaining conversation continuity via `--resume`.

## Purpose

- Maintain a registry of session metadata (path, mode, status, SDK session ID)
- Spawn Claude CLI processes for individual messages
- Convert Claude CLI stdout JSON lines to StreamEvent objects
- Handle message queuing when Claude is busy
- Manage process lifecycle (spawn, monitor, interrupt, kill)
- Track client connection state for response buffering

## Architecture: Per-Message Spawn

Rather than maintaining long-running Claude CLI processes, the SessionPool spawns a fresh process for each message:

```
claude --print "user message" \
       --output-format stream-json \
       --verbose \
       [--resume <sdkSessionId>] \
       [--dangerously-skip-permissions]
```

**Why per-message spawn?**
- Claude CLI (v2.1.76+) does not support `--input-format stream-json` without `--print`
- Each process lives only for the duration of one message exchange
- The `--resume` flag maintains conversation context by referencing the SDK session ID from the previous interaction

## Internal Types

### InternalSession

Extends `ManagedSession` with runtime state:

```typescript
interface InternalSession extends ManagedSession {
    process: ChildProcess | null;  // Currently running Claude process
    queue: MessageQueue;           // Per-session message queue
    processing: boolean;           // Whether a message is being processed
    model: string | null;          // Model name from Claude CLI init
}
```

## Key Methods

### `create(path: string, mode: PermissionMode) -> string`

Creates a new session. This is **lightweight** -- it only registers session metadata:

1. Validates that the project path exists on the filesystem
2. Generates a UUID for the session ID
3. Creates an `InternalSession` with status `idle`, no process, and a fresh `MessageQueue`
4. Returns the session ID

No Claude CLI process is spawned at this point.

### `send(sessionId: string, message: string) -> AsyncGenerator<StreamEvent>`

Sends a message to a session. Returns an async generator that yields stream events.

**If Claude is busy** (another message is being processed):
- Enqueues the message via `MessageQueue.enqueueUser()`
- Yields a single `queued` event with the queue position
- Returns immediately

**If Claude is idle:**
- Delegates to `processMessage()` which spawns a Claude process

### `processMessage(session, message) -> AsyncGenerator<StreamEvent>`

Internal method that spawns a Claude CLI process and yields events.

**Process spawn:**

```typescript
const child = spawn("claude", args, {
    cwd: session.path,
    stdio: ["pipe", "pipe", "pipe"],
    env: { ...process.env, TERM: "dumb" },
});
```

The `TERM: "dumb"` environment variable prevents Claude CLI from outputting ANSI escape codes.

**CLI arguments built from session state:**
- `--print <message>` -- The user's message
- `--output-format stream-json` -- JSON-lines output
- `--verbose` -- Include system messages
- `--resume <sdkSessionId>` -- Continue previous conversation (if available)
- `--dangerously-skip-permissions` -- Only in `auto` mode

**Stdin** is closed immediately (`child.stdin.end()`), since `--print` mode reads the prompt from arguments.

**Event processing:**

stdout is read line-by-line using Node.js `readline.createInterface()`. Each line is parsed as JSON (`ClaudeStdoutMessage`) and converted to a `StreamEvent` via `convertToStreamEvent()`.

Events are pushed to an internal queue. The async generator yields events as they arrive, using a promise-based wait mechanism for backpressure.

**Terminal events:** The generator breaks on `result`, `error`, or `interrupted` events.

**Cleanup:**
- `session.process` is set to null
- `session.processing` is set to false
- `session.status` is set to `idle`
- If the process is still alive, SIGTERM is sent (with a 3-second SIGKILL fallback)
- If queued messages exist, the next one is auto-processed via `processQueuedMessage()`

### `convertToStreamEvent(msg: ClaudeStdoutMessage) -> StreamEvent`

Maps Claude CLI stdout JSON messages to the internal StreamEvent format:

| Claude CLI Type | StreamEvent Type | Content |
|---|---|---|
| `system` (init) | `system` | Model name, session ID |
| `assistant` (text blocks) | `text` | Concatenated text content |
| `assistant` (tool blocks) | `tool_use` | Tool name, input data |
| `stream_event` (content_block_delta, text) | `partial` | Text delta |
| `stream_event` (content_block_delta, partial_json) | `partial` | Partial JSON |
| `stream_event` (content_block_start, tool_use) | `tool_use` | Tool name |
| `tool_progress` | `tool_use` | Tool name, status message |
| `result` | `result` | Session ID |

The `session_id` field from `result` events is captured and stored as `session.sdkSessionId` for future `--resume` calls.

### `resume(sessionId, sdkSessionId?) -> { ok, fallback }`

Resumes a session. In per-message spawn mode, this simply updates the `sdkSessionId` so the next `send()` will use `--resume`. Also calls `queue.onClientReconnect()`.

### `destroy(sessionId) -> boolean`

Destroys a session:
1. Kills any running Claude process (SIGTERM, then SIGKILL after 5 seconds)
2. Sets status to `destroyed`
3. Clears the message queue
4. Removes the session from the pool

### `setMode(sessionId, mode) -> boolean`

Updates the permission mode for a session. Takes effect on the next `send()` (next process spawn).

### `interrupt(sessionId) -> boolean`

Interrupts the current Claude operation:
1. Sends SIGTERM to the running Claude CLI process
2. Clears the message queue
3. Returns `true` if there was an active operation to interrupt

### `listSessions() -> SessionInfo[]`

Returns info for all sessions: sessionId, path, status, mode, sdkSessionId, model, createdAt, lastActivityAt.

### `clientDisconnect(sessionId)` / `bufferEvent(sessionId, event)` / `clientReconnect(sessionId)`

Proxy methods for MessageQueue's client connection state management. Used by server.ts when the SSE connection drops.

### `getQueueStats(sessionId) -> { userPending, responsePending, clientConnected }`

Returns queue statistics for a session.

### `destroyAll() -> void`

Destroys all sessions. Called during daemon shutdown.

## Connection to Other Modules

- **server.ts** creates a single `SessionPool` instance and calls its methods for all session-related RPC handlers
- Uses **MessageQueue** for per-session message buffering
- Imports types from **types.ts** (ManagedSession, SessionInfo, StreamEvent, PermissionMode, etc.)
