# Daemon Client (daemon_client.py)

**File:** `head/daemon_client.py`

JSON-RPC client for communicating with the Remote Agent Daemon over SSH tunnels. Handles both regular JSON responses and SSE (Server-Sent Events) streaming responses.

## Purpose

- Send JSON-RPC requests to the daemon's HTTP endpoint
- Parse SSE streams for `session.send` (streaming Claude responses)
- Provide typed methods for each RPC operation
- Handle connection errors and daemon-reported errors

## Class: DaemonClient

```python
class DaemonClient:
    timeout: int = 300  # Default timeout in seconds
```

### Internal Methods

#### `_url(local_port: int) -> str`

Builds the RPC endpoint URL: `http://127.0.0.1:{local_port}/rpc`

#### `_rpc_call(local_port, method, params) -> dict`

Makes a JSON-RPC call with the given method and parameters. Uses a 30-second timeout for non-streaming calls. Raises `DaemonError` if the response contains an error, or `DaemonConnectionError` if the HTTP request fails.

### Session Management Methods

#### `create_session(local_port, path, mode) -> str`

Creates a new Claude session on the remote machine.

- **Params:** `path` (project directory), `mode` (permission mode)
- **Returns:** `sessionId` (UUID string)

#### `send_message(local_port, session_id, message, idle_timeout) -> AsyncIterator[dict]`

Sends a message to a Claude session and streams back events via SSE.

This is the core method for interacting with Claude. It:

1. Sends a `session.send` JSON-RPC request
2. Reads the response as an SSE stream (`text/event-stream`)
3. Parses each `data: {...}` line as JSON
4. Yields parsed event dicts to the caller
5. Returns when it receives `data: [DONE]`

**Timeout behavior:**
- Total timeout: 15 minutes (900 seconds)
- Idle timeout (per-read): configurable, defaults to 300 seconds (5 minutes)
- If no events are received within the idle timeout, yields an error event

**Error handling:**
- `asyncio.TimeoutError` -> yields an error event about stream idle timeout
- `aiohttp.ClientError` -> yields a connection error event

#### `resume_session(local_port, session_id, sdk_session_id) -> dict`

Resumes a previously detached session. If `sdk_session_id` is provided, it is passed to the daemon to set up `--resume` for future Claude invocations.

Returns a dict with `ok` (bool) and `fallback` (bool indicating if a fresh session was created with history injection).

#### `destroy_session(local_port, session_id) -> bool`

Destroys a session and kills any running Claude process. Returns `True` on success.

#### `list_sessions(local_port) -> list[dict]`

Lists all sessions on a remote daemon. Returns a list of session info dicts.

#### `set_mode(local_port, session_id, mode) -> bool`

Sets the permission mode for a session. Returns `True` on success.

#### `interrupt_session(local_port, session_id) -> dict`

Interrupts the current Claude operation for a session by sending SIGTERM to the Claude CLI process. Returns a dict with:
- `ok` (bool): Always `True` if the session exists
- `interrupted` (bool): `True` if there was an active operation to interrupt

#### `health_check(local_port) -> dict`

Checks daemon health. Returns session counts, uptime, memory usage, daemon version, and PID.

#### `monitor_sessions(local_port) -> dict`

Gets detailed monitoring information for all sessions, including queue stats.

#### `reconnect_session(local_port, session_id) -> list[dict]`

Reconnects to a session and retrieves any buffered events that were generated while the client was disconnected.

#### `get_queue_stats(local_port, session_id) -> dict`

Gets message queue statistics for a session: pending user messages, pending responses, and client connection state.

### Cleanup

#### `close() -> None`

Closes the underlying aiohttp session. Called during Head Node shutdown.

## Exception Classes

### `DaemonError`

Raised when the daemon returns an error response in the JSON-RPC result.

```python
class DaemonError(Exception):
    code: int  # Error code from daemon
```

### `DaemonConnectionError`

Raised when the HTTP connection to the daemon fails (network error, connection refused, etc.).

## Connection to Other Modules

- **main.py** creates the DaemonClient and calls `close()` on shutdown
- **BotBase** calls all session management methods in response to user commands and message forwarding
- **SSHManager** provides the `local_port` that maps to the remote daemon via SSH tunnel
