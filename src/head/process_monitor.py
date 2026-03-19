"""Process monitoring utilities for Codecast components.

Provides helpers to check PID liveness, read PID/port files, perform daemon
health checks, and locate processes by name.  These were originally private
helpers inside ``cli.py``; extracting them here lets both the CLI and the TUI
share them without importing private names.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Well-known file paths
# ---------------------------------------------------------------------------

CODECAST_DIR: Path = Path.home() / ".codecast"
PORT_FILE: Path = CODECAST_DIR / "daemon.port"
DAEMON_PID_FILE: Path = CODECAST_DIR / "daemon.pid"
HEAD_PID_FILE: Path = CODECAST_DIR / "head.pid"
WEBUI_PID_FILE: Path = CODECAST_DIR / "webui.pid"
WEBUI_PORT_FILE: Path = CODECAST_DIR / "webui.port"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def pid_alive(pid: int) -> bool:
    """Return True if a process with *pid* exists."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def read_pid_file(path: Path) -> int | None:
    """Read a PID from a file, returning None if missing or invalid."""
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def read_port_file() -> int | None:
    """Return the daemon port from the port file, or None."""
    try:
        return int(PORT_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def daemon_healthy(port: int) -> bool:
    """Quick health check against localhost:<port> via JSON-RPC."""
    try:
        payload = json.dumps({"jsonrpc": "2.0", "method": "health.check", "params": {}, "id": "1"}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/rpc",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def find_process(name: str) -> int | None:
    """Find a process by name using pgrep, returning its PID or None."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", name],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            # Return first PID (skip our own)
            for line in result.stdout.strip().splitlines():
                pid = int(line.strip())
                if pid != os.getpid():
                    return pid
    except (FileNotFoundError, ValueError):
        pass
    return None
