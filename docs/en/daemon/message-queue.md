# Message Queue (message-queue.ts)

**File:** `daemon/src/message-queue.ts`

Per-session message queue with three responsibilities: buffering user messages when Claude is busy, buffering responses when the SSH connection is down, and tracking client connection state.

## Purpose

- **User message buffering**: When Claude is processing a message, additional user messages are queued and processed in order after the current message completes.
- **Response buffering**: When the SSH connection (and thus the SSE stream) drops mid-response, events are buffered and can be replayed when the client reconnects.
- **Client connection tracking**: Tracks whether the Head Node client is currently connected, so the system knows whether to buffer responses.

## Class: MessageQueue

```typescript
class MessageQueue {
    private userPending: QueuedUserMessage[];   // Queued user messages
    private responsePending: QueuedResponse[];  // Buffered response events
    private _clientConnected: boolean;          // Client connection state
}
```

Each session has its own MessageQueue instance, created when the session is created.

## User Message Buffering

### `enqueueUser(message: string) -> number`

Adds a user message to the queue. Returns the queue position (1-based). Called by `SessionPool.send()` when Claude is already processing a message.

### `dequeueUser() -> QueuedUserMessage | null`

Removes and returns the next user message from the queue. Returns `null` if the queue is empty. Called by `SessionPool.processMessage()` after completing a message to check if there's another message to process.

### `hasUserPending() -> boolean`

Returns `true` if there are queued user messages waiting to be processed.

### `userQueueLength` (getter)

Returns the number of pending user messages.

## Response Buffering

### `bufferResponse(event: StreamEvent, force: boolean = false) -> void`

Buffers a response event. By default, events are only buffered when `_clientConnected` is `false`. The `force` parameter bypasses this check -- used by server.ts when it detects the SSE client has disconnected but the session pool hasn't been notified yet.

### `replayResponses() -> StreamEvent[]`

Returns all buffered response events and clears the buffer. Called during client reconnection to replay any events that were generated while the client was disconnected.

### `hasResponsesPending() -> boolean`

Returns `true` if there are buffered response events.

## Client Connection State

### `clientConnected` (getter)

Returns the current client connection state.

### `onClientDisconnect() -> void`

Marks the client as disconnected. After this call, response events will be buffered instead of being assumed delivered. Called by the server when the SSE response stream's `close` event fires.

### `onClientReconnect() -> StreamEvent[]`

Marks the client as reconnected and returns all buffered response events (combining the reconnect notification with response replay). Called by `session.reconnect` RPC handler.

## Cleanup

### `clear() -> void`

Clears both the user message queue and the response buffer. Called when a session is destroyed or interrupted.

### `stats() -> { userPending, responsePending, clientConnected }`

Returns queue statistics for debugging and monitoring. Used by the `/status` and `/monitor` commands.

## Data Types

### QueuedUserMessage

```typescript
interface QueuedUserMessage {
    message: string;    // The user's message text
    timestamp: number;  // Date.now() when enqueued
}
```

### QueuedResponse

```typescript
interface QueuedResponse {
    event: StreamEvent;  // The response event
    timestamp: number;   // Date.now() when buffered
}
```

## Flow Example

```
User sends msg1 -> Claude starts processing
User sends msg2 -> enqueueUser("msg2"), position=1
User sends msg3 -> enqueueUser("msg3"), position=2
Claude finishes msg1 -> dequeueUser() returns msg2
                     -> Claude starts processing msg2
SSH drops mid-stream  -> onClientDisconnect()
                     -> subsequent events buffered via bufferResponse()
Claude finishes msg2  -> dequeueUser() returns msg3
                     -> Claude starts processing msg3
SSH reconnects        -> session.reconnect RPC
                     -> onClientReconnect() returns buffered events
```

## Connection to Other Modules

- **session-pool.ts** creates a MessageQueue per session and calls its methods for message queuing and client state management
- Imports **StreamEvent**, **QueuedUserMessage**, and **QueuedResponse** from **types.ts**
