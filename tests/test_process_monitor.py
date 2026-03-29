"""Tests for head.process_monitor – shared process monitoring utilities."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from head.process_monitor import (
    CODECAST_DIR,
    DAEMON_PID_FILE,
    HEAD_PID_FILE,
    PORT_FILE,
    WEBUI_PID_FILE,
    WEBUI_PORT_FILE,
    daemon_healthy,
    find_all_processes,
    find_process,
    pid_alive,
    read_pid_file,
    read_port_file,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_codecast_dir_is_under_home(self):
        assert CODECAST_DIR == Path.home() / ".codecast"

    def test_daemon_pid_file(self):
        assert DAEMON_PID_FILE == CODECAST_DIR / "daemon.pid"

    def test_head_pid_file(self):
        assert HEAD_PID_FILE == CODECAST_DIR / "head.pid"

    def test_webui_pid_file(self):
        assert WEBUI_PID_FILE == CODECAST_DIR / "webui.pid"

    def test_webui_port_file(self):
        assert WEBUI_PORT_FILE == CODECAST_DIR / "webui.port"

    def test_port_file(self):
        assert PORT_FILE == CODECAST_DIR / "daemon.port"


# ---------------------------------------------------------------------------
# pid_alive
# ---------------------------------------------------------------------------


class TestPidAlive:
    def test_current_process_is_alive(self):
        assert pid_alive(os.getpid()) is True

    def test_nonexistent_pid_is_not_alive(self):
        # PID 0 is kernel; sending signal 0 to a very high PID should fail
        assert pid_alive(4_000_000) is False

    def test_permission_error_returns_false(self):
        with patch("os.kill", side_effect=PermissionError):
            assert pid_alive(1) is False


# ---------------------------------------------------------------------------
# read_pid_file
# ---------------------------------------------------------------------------


class TestReadPidFile:
    def test_reads_valid_pid(self, tmp_path):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345\n")
        assert read_pid_file(pid_file) == 12345

    def test_returns_none_for_missing_file(self, tmp_path):
        assert read_pid_file(tmp_path / "nonexistent.pid") is None

    def test_returns_none_for_invalid_content(self, tmp_path):
        pid_file = tmp_path / "bad.pid"
        pid_file.write_text("not-a-number\n")
        assert read_pid_file(pid_file) is None

    def test_strips_whitespace(self, tmp_path):
        pid_file = tmp_path / "ws.pid"
        pid_file.write_text("  42  \n")
        assert read_pid_file(pid_file) == 42


# ---------------------------------------------------------------------------
# read_port_file
# ---------------------------------------------------------------------------


class TestReadPortFile:
    def test_returns_none_when_no_port_file(self):
        with patch("head.process_monitor.PORT_FILE", Path("/tmp/_nonexistent_codecast_port")):
            assert read_port_file() is None

    def test_reads_port_from_file(self, tmp_path):
        port_file = tmp_path / "daemon.port"
        port_file.write_text("9100\n")
        with patch("head.process_monitor.PORT_FILE", port_file):
            assert read_port_file() == 9100


# ---------------------------------------------------------------------------
# daemon_healthy
# ---------------------------------------------------------------------------


class TestDaemonHealthy:
    def test_returns_false_for_unreachable_port(self):
        # Port 1 is almost certainly not serving JSON-RPC
        assert daemon_healthy(1) is False

    def test_returns_true_on_200(self):
        class FakeResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        with patch("urllib.request.urlopen", return_value=FakeResp()):
            assert daemon_healthy(9100) is True

    def test_returns_false_on_exception(self):
        with patch("urllib.request.urlopen", side_effect=ConnectionError):
            assert daemon_healthy(9100) is False


# ---------------------------------------------------------------------------
# find_process
# ---------------------------------------------------------------------------


class TestFindProcess:
    def test_returns_none_when_pgrep_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert find_process("nonexistent-xyz") is None

    def test_returns_pid_from_pgrep_output(self):
        class FakeResult:
            returncode = 0
            stdout = "9999\n"

        with patch("subprocess.run", return_value=FakeResult()), patch("os.getpid", return_value=1):
            assert find_process("some-daemon") == 9999

    def test_skips_own_pid(self):
        own_pid = os.getpid()

        class FakeResult:
            returncode = 0
            stdout = f"{own_pid}\n8888\n"

        with patch("subprocess.run", return_value=FakeResult()):
            assert find_process("some-daemon") == 8888

    def test_returns_none_when_no_match(self):
        class FakeResult:
            returncode = 1
            stdout = ""

        with patch("subprocess.run", return_value=FakeResult()):
            assert find_process("nonexistent") is None


# ---------------------------------------------------------------------------
# find_all_processes
# ---------------------------------------------------------------------------


class TestFindAllProcesses:
    def test_returns_empty_list_when_no_processes(self):
        result = find_all_processes("__nonexistent_process_xyz__")
        assert result == []

    def test_returns_list_of_pids(self):
        class FakeResult:
            returncode = 0
            stdout = "1111\n2222\n3333\n"

        with patch("subprocess.run", return_value=FakeResult()), patch("os.getpid", return_value=9999):
            result = find_all_processes("some-daemon")
            assert result == [1111, 2222, 3333]

    def test_excludes_own_pid(self):
        own_pid = os.getpid()

        class FakeResult:
            returncode = 0
            stdout = f"{own_pid}\n8888\n7777\n"

        with patch("subprocess.run", return_value=FakeResult()):
            result = find_all_processes("some-daemon")
            assert own_pid not in result
            assert 8888 in result
            assert 7777 in result

    def test_returns_empty_on_pgrep_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert find_all_processes("anything") == []

    def test_returns_empty_on_no_match(self):
        class FakeResult:
            returncode = 1
            stdout = ""

        with patch("subprocess.run", return_value=FakeResult()):
            assert find_all_processes("nonexistent") == []


# ---------------------------------------------------------------------------
# Backward compatibility: cli.py re-exports
# ---------------------------------------------------------------------------


class TestCliBackwardCompat:
    """Ensure cli.py still exposes the underscore-prefixed aliases."""

    def test_constants_importable(self):
        from head.cli import _DAEMON_PID_FILE, _HEAD_PID_FILE, _WEBUI_PID_FILE, _WEBUI_PORT_FILE

        assert _DAEMON_PID_FILE == DAEMON_PID_FILE
        assert _HEAD_PID_FILE == HEAD_PID_FILE
        assert _WEBUI_PID_FILE == WEBUI_PID_FILE
        assert _WEBUI_PORT_FILE == WEBUI_PORT_FILE

    def test_functions_importable(self):
        from head.cli import _daemon_healthy, _find_process, _pid_alive, _read_pid_file, _read_port_file

        assert _pid_alive is pid_alive
        assert _read_pid_file is read_pid_file
        assert _read_port_file is read_port_file
        assert _daemon_healthy is daemon_healthy
        assert _find_process is find_process
