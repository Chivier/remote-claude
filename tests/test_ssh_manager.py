"""Tests for SSHManager daemon version checking."""

import json
import pytest

from head.ssh_manager import _parse_health_response


class TestCheckDaemonHealthVersion:
    """Tests for _parse_health_response."""

    def test_parses_version_from_health_response(self):
        response = json.dumps({"ok": True, "version": "0.2.22", "pid": 1234})
        ok, version = _parse_health_response(response)
        assert ok is True
        assert version == "0.2.22"

    def test_healthy_without_version_field(self):
        response = json.dumps({"ok": True, "pid": 1234})
        ok, version = _parse_health_response(response)
        assert ok is True
        assert version is None

    def test_unhealthy_response(self):
        response = '{"ok":false}'
        ok, version = _parse_health_response(response)
        assert ok is False
        assert version is None

    def test_empty_response(self):
        ok, version = _parse_health_response("")
        assert ok is False
        assert version is None

    def test_garbage_response(self):
        ok, version = _parse_health_response("curl: (7) Failed to connect")
        assert ok is False
        assert version is None
