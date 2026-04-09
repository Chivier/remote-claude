"""Tests for SSHManager daemon version checking."""

import json
import pytest

from head.ssh_manager import TunnelResult, _parse_health_response


class TestTunnelResult:
    def test_default_no_upgrade(self):
        r = TunnelResult(local_port=19100)
        assert r.daemon_upgraded is False
        assert r.old_version is None
        assert r.new_version is None

    def test_upgrade_fields(self):
        r = TunnelResult(local_port=19100, daemon_upgraded=True, old_version="0.2.21", new_version="0.2.22")
        assert r.daemon_upgraded is True
        assert r.old_version == "0.2.21"
        assert r.new_version == "0.2.22"


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
