# Type Definitions (types.ts)

**File:** `daemon/src/types.ts`

Central type definitions for the daemon's RPC protocol, session management, stream events, and Claude CLI JSON-lines format.

## Purpose

- Define the JSON-RPC request/response wire format
- Define session status and permission mode enumerations
- Map permission modes to Claude CLI flags
- Define stream event types for SSE communication
- Define Claude CLI stdout message format
- Define typed parameter and result interfaces for each RPC method

## RPC Protocol Types

### RpcRequest

```typescript
interface RpcRequest {
    method: string;                    // e.g., "session.create"
    params?: Record<string, unknown>;  // Method parameters
    id?: string;                       // Optional request ID
}
```

### RpcResponse

```typescript
interface RpcResponse {
    result?: unknown;                           // Success result
    error?: { code: number; message: string; data?: unknown };  // Error
    id?: string;                                // Echoed request ID
}
```

## Session Types

### SessionStatus

```typescript
type SessionStatus = "idle" | "busy" | "error" | "destroyed";
```

- **idle**: No Claude process running, ready for messages
- **busy**: A Claude process is currently handling a message
- **error**: Session encountered an error
- **destroyed**: Session has been destroyed and cleaned up

### PermissionMode

```typescript
type PermissionMode = "auto" | "code" | "plan" | "ask";
```

### `modeToCliFlag(mode: PermissionMode) -> string[]`

Maps internal mode names to Claude CLI flags:

| Mode | CLI Flags | Effect |
|---|---|---|
| `auto` | `["--dangerously-skip-permissions"]` | Full automation, no confirmation prompts |
| `code` | `[]` | No specific CLI flag (SDK-level) |
| `plan` | `[]` | No specific CLI flag (SDK-level) |
| `ask` | `[]` | Default behavior (all tools need confirmation) |

Currently, only `auto` mode has a corresponding CLI flag. The `code` and `plan` modes are SDK-level concepts that don't have direct Claude CLI `--print` mode equivalents.

### ManagedSession

Base session interface:

```typescript
interface ManagedSession {
    sessionId: string;
    path: string;
    mode: PermissionMode;
    status: SessionStatus;
    sdkSessionId: string | null;
    createdAt: Date;
    lastActivityAt: Date;
}
```

### SessionInfo

Serializable session info (dates as ISO strings):

```typescript
interface SessionInfo {
    sessionId: string;
    path: string;
    status: SessionStatus;
    mode: PermissionMode;
    sdkSessionId: string | null;
    model: string | null;
    createdAt: string;      // ISO 8601
    lastActivityAt: string;  // ISO 8601
}
```

## Stream Event Types

### StreamEventType

```typescript
type StreamEventType =
    | "text"        // Complete text block
    | "tool_use"    // Tool invocation
    | "tool_result" // Tool execution result
    | "result"      // Final result with session_id
    | "queued"      // Message queued (Claude busy)
    | "error"       // Error message
    | "system"      // System event (init, etc.)
    | "partial"     // Streaming text delta
    | "ping"        // Keepalive
    | "interrupted"; // Operation was interrupted
```

### StreamEvent

```typescript
interface StreamEvent {
    type: StreamEventType;
    content?: string;       // Text content (for text/partial)
    tool?: string;          // Tool name (for tool_use)
    input?: unknown;        // Tool input (for tool_use)
    output?: unknown;       // Tool output (for tool_result)
    session_id?: string;    // SDK session ID (for result/system)
    position?: number;      // Queue position (for queued)
    message?: string;       // Error/status message
    subtype?: string;       // Event subtype (for system: "init")
    model?: string;         // Model name (for system init)
    raw?: unknown;          // Raw Claude CLI data (passthrough)
}
```

## Message Queue Types

### QueuedUserMessage

```typescript
interface QueuedUserMessage {
    message: string;    // User message text
    timestamp: number;  // Date.now()
}
```

### QueuedResponse

```typescript
interface QueuedResponse {
    event: StreamEvent;  // Buffered response event
    timestamp: number;   // Date.now()
}
```

## RPC Method Parameters & Results

### Session Methods

```typescript
interface CreateSessionParams {
    path: string;
    mode?: PermissionMode;
}

interface CreateSessionResult {
    sessionId: string;
}

interface SendMessageParams {
    sessionId: string;
    message: string;
}

interface ResumeSessionParams {
    sessionId: string;
    sdkSessionId?: string;
}

interface ResumeSessionResult {
    ok: boolean;
    fallback?: boolean;
    newSdkSessionId?: string;
}

interface DestroySessionParams {
    sessionId: string;
}

interface SetModeParams {
    sessionId: string;
    mode: PermissionMode;
}

interface InterruptSessionParams {
    sessionId: string;
}
```

### Health & Monitor

```typescript
interface HealthCheckResult {
    ok: boolean;
    sessions: number;
    sessionsByStatus: Record<string, number>;
    uptime: number;        // seconds
    memory: {
        rss: number;       // MB
        heapUsed: number;  // MB
        heapTotal: number; // MB
    };
    nodeVersion: string;
    pid: number;
}

interface MonitorSessionDetail {
    sessionId: string;
    path: string;
    status: SessionStatus;
    mode: PermissionMode;
    model: string | null;
    sdkSessionId: string | null;
    createdAt: string;
    lastActivityAt: string;
    queue: {
        userPending: number;
        responsePending: number;
        clientConnected: boolean;
    };
}

interface MonitorSessionsResult {
    sessions: MonitorSessionDetail[];
    totalSessions: number;
    uptime: number;  // seconds
}
```

## Claude CLI JSON-Lines Protocol

### ClaudeStdoutMessage

The raw message format from Claude CLI's `--output-format stream-json` output:

```typescript
interface ClaudeStdoutMessage {
    type: string;           // "system", "assistant", "stream_event", "result", "tool_progress"
    subtype?: string;       // "init" for system messages
    session_id?: string;    // SDK session ID

    // Assistant message content
    message?: {
        role: string;
        content: Array<{
            type: string;    // "text" or "tool_use"
            text?: string;
            name?: string;   // tool name
            input?: unknown; // tool input
            id?: string;
        }>;
    };

    // Streaming events
    event?: {
        type: string;        // "content_block_delta", "content_block_start"
        index?: number;
        delta?: {
            type?: string;
            text?: string;
            partial_json?: string;
        };
        content_block?: {
            type: string;    // "text" or "tool_use"
            text?: string;
            name?: string;
            id?: string;
        };
    };

    // Result metadata
    duration_ms?: number;
    usage?: {
        input_tokens: number;
        output_tokens: number;
    };

    // Tool progress
    tool_name?: string;
    status?: string;
}
```

Note: `ClaudeStdinMessage` was removed from the type definitions since the daemon uses `--print` mode (per-message spawn) instead of stdin JSON-lines.

## Connection to Other Modules

- **All daemon modules** import types from this file
- **server.ts** uses RPC request/response types and parameter interfaces
- **session-pool.ts** uses session types, stream events, and the mode-to-flag mapping
- **message-queue.ts** uses queue types and StreamEvent
