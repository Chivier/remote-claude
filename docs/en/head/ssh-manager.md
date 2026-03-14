# SSH Manager (ssh_manager.py)

**File:** `head/ssh_manager.py`

Manages SSH connections, port-forwarding tunnels, remote daemon deployment, and skills synchronization. This is the bridge between the local Head Node and remote machines.

## Purpose

- Maintain a pool of SSH connections and tunnels to remote machines
- Create local port-forwarding tunnels to access remote daemons
- Deploy daemon code to remote machines via SCP
- Start and health-check daemons on remote machines
- Sync skills files to remote project directories
- List machines with their online/daemon status

## Classes

### SSHTunnel

Represents an active SSH tunnel to a remote machine.

```python
class SSHTunnel:
    machine_id: str          # Machine this tunnel connects to
    local_port: int          # Local port (e.g., 19100)
    conn: SSHClientConnection  # asyncssh connection
    listener: SSHListener    # Port forwarding listener
```

**Properties:**
- `alive` -- Returns `True` if the underlying SSH connection is still open.

**Methods:**
- `close()` -- Closes the port forwarding listener and SSH connection.

### SSHManager

Main class managing all SSH operations.

```python
class SSHManager:
    config: Config
    machines: dict[str, MachineConfig]
    tunnels: dict[str, SSHTunnel]      # machine_id -> active tunnel
```

## Key Methods

### `ensure_tunnel(machine_id: str) -> int`

Ensures an SSH tunnel exists to the specified machine. Returns the local port number for accessing the daemon.

**Flow:**
1. Check if a tunnel already exists and is alive -- return existing local port
2. If the tunnel is dead, close and remove it
3. Allocate a new local port (starting from 19100, incrementing)
4. Establish SSH connection via `_connect_ssh()`
5. Create local port forwarding: `127.0.0.1:<local_port>` -> `127.0.0.1:<daemon_port>`
6. Ensure the daemon is running on the remote machine via `_ensure_daemon()`
7. Store the tunnel and return the local port

### `_connect_ssh(machine: MachineConfig) -> SSHClientConnection`

Establishes an SSH connection to a machine. Handles:

- **SSH key authentication**: Uses `client_keys` if `ssh_key` is configured
- **Password authentication**: Supports direct passwords and `file:/path` syntax
- **ProxyJump**: Connects through a jump host by first establishing a connection to the jump machine, then using it as a `tunnel` for the final connection
- **Known hosts**: Disabled (`known_hosts=None`) for simplicity in trusted environments

### `_ensure_daemon(machine_id: str, conn: SSHClientConnection) -> None`

Ensures the daemon process is running on the remote machine.

**Flow:**
1. Check if a `node.*dist/server.js` process is already running via `pgrep`
2. If running, return immediately
3. Check if daemon code exists at `install_dir` (both `dist/server.js` and `node_modules/`)
4. If missing and `auto_deploy` is enabled, call `_deploy_daemon()`
5. Start the daemon with `nohup`, setting:
   - `DAEMON_PORT` environment variable
   - `PATH` including the Node.js binary directory and `~/.local/bin` (for Claude CLI)
6. Poll the health endpoint (`health.check` RPC) every 2 seconds for up to 30 seconds
7. Raise `RuntimeError` if the daemon does not respond within the timeout

### `_deploy_daemon(machine_id: str, conn: SSHClientConnection) -> None`

Deploys daemon code to a remote machine via SCP.

**Flow:**
1. Build the daemon locally if `daemon/dist/` does not exist (`npm run build`)
2. Create the remote install directory
3. SCP `package.json` and `package-lock.json` to the remote
4. SCP the entire `dist/` directory recursively
5. Run `npm install --production` on the remote machine
6. If npm is in a non-standard location, derive its path from `node_path`

### `sync_skills(machine_id: str, remote_path: str) -> None`

Syncs skills files from the local `skills.shared_dir` to a remote project path.

**Behavior:**
- Skips entirely if `skills.sync_on_start` is `false`
- Copies `CLAUDE.md` to the remote project root, but only if it does not already exist there
- Copies the `.claude/skills/` directory recursively to the remote project
- Uses existing SSH tunnel connection if available, otherwise creates a new connection
- Errors are logged as warnings and do not fail the session creation

### `list_machines() -> list[dict]`

Lists all configured machines with their online and daemon status.

**Behavior:**
- Skips machines that are only used as jump hosts (referenced by `proxy_jump` and having no `default_paths`)
- For each machine, attempts an SSH connection with a 15-second timeout
- If reachable, checks if the daemon process is running via `pgrep`
- Returns a list of dicts with: `id`, `host`, `user`, `status` (online/offline), `daemon` (running/stopped/unknown), `default_paths`

### `get_local_port(machine_id: str) -> Optional[int]`

Returns the local tunnel port for a machine if a live tunnel exists, otherwise `None`.

### `close_all() -> None`

Closes all SSH tunnels and connections. Called during graceful shutdown.

## Port Allocation

Local ports for SSH tunnels are allocated sequentially starting from `19100`:

```
gpu-1 -> localhost:19100
gpu-2 -> localhost:19101
gpu-3 -> localhost:19102
...
```

This simple allocation works because the Head Node manages all tunnels in a single process.

## Connection to Other Modules

- **main.py** creates the SSHManager with the full config and calls `close_all()` on shutdown
- **BotBase** calls `ensure_tunnel()` before every daemon RPC call and `sync_skills()` on `/start`
- **BotBase** calls `list_machines()` for the `/ls machine` command
- **BotBase** calls `get_local_port()` for the `/health` command when checking all connected machines
