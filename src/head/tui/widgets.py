"""Custom widgets for the Codecast TUI dashboard."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from textual.widgets import DataTable, Static

from head.process_monitor import (
    DAEMON_PID_FILE,
    HEAD_PID_FILE,
    WEBUI_PID_FILE,
    WEBUI_PORT_FILE,
    daemon_healthy,
    find_process,
    pid_alive,
    read_pid_file,
    read_port_file,
)


class StatusPanel(Static):
    """Displays component status with colored indicators."""

    DEFAULT_CSS = """
    StatusPanel {
        padding: 0 1;
    }
    """

    REFRESH_INTERVAL = 2.0  # seconds between auto-refresh

    def __init__(self, config_path: str = "", **kwargs) -> None:
        super().__init__("", **kwargs)
        self.config_path = config_path

    def on_mount(self) -> None:
        self.update(self._build_status())
        self.set_interval(self.REFRESH_INTERVAL, self.refresh_status)

    def _get_bot_summary(self) -> list[str]:
        """Return list of configured bot descriptions from config."""
        if not self.config_path:
            return []
        try:
            from head.config import load_config_v2

            cfg = load_config_v2(self.config_path)
        except Exception:
            return []
        bots: list[str] = []
        if cfg.bot:
            if cfg.bot.discord and getattr(cfg.bot.discord, "token", None):
                bots.append("Discord")
            if cfg.bot.telegram and getattr(cfg.bot.telegram, "token", None):
                bots.append("Telegram")
            if getattr(cfg.bot, "lark", None) and getattr(cfg.bot.lark, "app_id", None):
                bots.append("Lark")
        return bots

    def _build_status(self) -> str:
        lines: list[str] = []

        # Head Node
        head_pid = read_pid_file(HEAD_PID_FILE)
        head_running = head_pid is not None and pid_alive(head_pid)
        if head_running:
            bots = self._get_bot_summary()
            bot_info = f" | bots: {', '.join(bots)}" if bots else ""
            lines.append(f"Head:   [green]●[/green] running (pid={head_pid}){bot_info}")
        else:
            lines.append("Head:   [dim]○[/dim] not running")

        # Daemon
        port = read_port_file()
        daemon_pid = read_pid_file(DAEMON_PID_FILE) or find_process("codecast-daemon")
        if port is not None and daemon_healthy(port):
            pid_part = f" (pid={daemon_pid})" if daemon_pid else ""
            lines.append(f"Daemon: [green]●[/green] running on port {port}{pid_part}")
        else:
            lines.append("Daemon: [dim]○[/dim] not running")

        # WebUI
        webui_pid = read_pid_file(WEBUI_PID_FILE)
        webui_port = read_pid_file(WEBUI_PORT_FILE)
        if webui_pid is not None and pid_alive(webui_pid):
            lines.append(f"WebUI:  [green]●[/green] running on http://127.0.0.1:{webui_port} (pid={webui_pid})")
        else:
            lines.append("WebUI:  [dim]○[/dim] not running")

        # Claude CLI
        claude_path = shutil.which("claude")
        if claude_path:
            lines.append(f"Claude: [green]✓[/green] available ({claude_path})")
        else:
            lines.append("Claude: [red]✗[/red] not found")

        return "\n".join(lines)

    def refresh_status(self) -> None:
        """Re-check and update all status indicators."""
        self.update(self._build_status())


class MachineTable(DataTable):
    """DataTable showing configured machines from config."""

    DEFAULT_CSS = """
    MachineTable {
        height: auto;
        max-height: 16;
    }
    """

    def __init__(self, config_path: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.config_path = config_path

    def on_mount(self) -> None:
        self.add_columns("Name", "Transport", "Host", "Port")
        self.cursor_type = "row"
        self._populate()

    def _populate(self) -> None:
        try:
            from head.config import load_config_v2

            cfg = load_config_v2(self.config_path)
            machines = getattr(cfg, "peers", {}) or {}
        except Exception:
            machines = {}

        for name, machine in machines.items():
            transport = getattr(machine, "transport", "?")
            if transport == "ssh":
                host = getattr(machine, "ssh_host", "") or ""
            elif transport == "http":
                host = getattr(machine, "address", "") or ""
            else:
                host = "localhost"

            # Truncate long hostnames
            if len(host) > 24:
                host = host[:21] + "..."

            port = str(getattr(machine, "port", 9100) or 9100)
            self.add_row(name, transport, host, port, key=name)

    @property
    def machine_count(self) -> int:
        return self.row_count

    def refresh_machines(self) -> None:
        """Clear and re-populate from config."""
        self.clear()
        self._populate()

    def get_selected_machine_name(self) -> str | None:
        """Return the name of the currently selected machine, or None."""
        if self.row_count == 0:
            return None
        try:
            row = self.get_row_at(self.cursor_row)
            # The first cell is the machine name
            return str(row[0]) if row else None
        except Exception:
            return None
