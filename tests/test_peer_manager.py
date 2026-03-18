"""Tests for PeerManager – central peer registry with transport creation."""

import pytest

from head.config import PeerConfig
from head.peer_manager import PeerManager
from head.transport.http import HTTPTransport
from head.transport.ssh import SSHTransport


# ── Fixtures ──


def _http_peer(peer_id: str = "web1") -> PeerConfig:
    return PeerConfig(
        id=peer_id,
        transport="http",
        address="10.0.0.1:9100",
        token="secret-token",
    )


def _ssh_peer(peer_id: str = "gpu1") -> PeerConfig:
    return PeerConfig(
        id=peer_id,
        transport="ssh",
        ssh_host="10.0.0.2",
        ssh_user="ubuntu",
        daemon_port=9100,
    )


def _local_peer(peer_id: str = "local1") -> PeerConfig:
    return PeerConfig(
        id=peer_id,
        transport="local",
        daemon_port=9100,
    )


# ── Registration tests ──


class TestRegister:
    def test_register_http_peer(self):
        mgr = PeerManager()
        peer = _http_peer()
        mgr.register(peer)
        assert "web1" in mgr.peers
        assert mgr.peers["web1"] is peer

    def test_register_ssh_peer(self):
        mgr = PeerManager()
        peer = _ssh_peer()
        mgr.register(peer)
        assert "gpu1" in mgr.peers
        assert mgr.peers["gpu1"] is peer

    def test_list_peers(self):
        mgr = PeerManager()
        mgr.register(_http_peer("a"))
        mgr.register(_ssh_peer("b"))
        result = mgr.list_peers()
        assert len(result) == 2
        ids = {p["id"] for p in result}
        assert ids == {"a", "b"}

    def test_remove_peer(self):
        mgr = PeerManager()
        mgr.register(_http_peer("x"))
        assert "x" in mgr.peers
        mgr.remove("x")
        assert "x" not in mgr.peers

    def test_remove_peer_clears_transport(self):
        mgr = PeerManager()
        mgr.register(_http_peer("x"))
        # Force transport creation
        _ = mgr.get_transport("x")
        assert "x" in mgr._transports
        mgr.remove("x")
        assert "x" not in mgr._transports

    def test_remove_nonexistent_peer_raises(self):
        mgr = PeerManager()
        with pytest.raises(KeyError):
            mgr.remove("nope")


# ── Transport creation tests ──


class TestGetTransport:
    def test_get_transport_http(self):
        mgr = PeerManager()
        mgr.register(_http_peer())
        transport = mgr.get_transport("web1")
        assert isinstance(transport, HTTPTransport)
        assert transport.peer_id == "web1"

    def test_get_transport_ssh(self):
        mgr = PeerManager()
        mgr.register(_ssh_peer())
        transport = mgr.get_transport("gpu1")
        assert isinstance(transport, SSHTransport)
        assert transport.peer_id == "gpu1"

    def test_get_transport_local(self):
        mgr = PeerManager()
        mgr.register(_local_peer())
        transport = mgr.get_transport("local1")
        assert isinstance(transport, HTTPTransport)
        assert transport.peer_id == "local1"
        # Local peers connect via plain HTTP to localhost
        assert "127.0.0.1" in transport.get_base_url()

    def test_get_transport_caches(self):
        mgr = PeerManager()
        mgr.register(_http_peer())
        t1 = mgr.get_transport("web1")
        t2 = mgr.get_transport("web1")
        assert t1 is t2

    def test_get_transport_unknown_peer_raises(self):
        mgr = PeerManager()
        with pytest.raises(KeyError):
            mgr.get_transport("unknown")

    def test_get_transport_unknown_transport_type_raises(self):
        mgr = PeerManager()
        peer = PeerConfig(id="bad", transport="carrier_pigeon")
        mgr.register(peer)
        with pytest.raises(ValueError, match="carrier_pigeon"):
            mgr.get_transport("bad")


# ── List peers detail ──


class TestListPeersDetail:
    def test_list_peers_includes_transport_type(self):
        mgr = PeerManager()
        mgr.register(_http_peer("h"))
        mgr.register(_ssh_peer("s"))
        mgr.register(_local_peer("l"))
        result = mgr.list_peers()
        by_id = {p["id"]: p for p in result}
        assert by_id["h"]["transport"] == "http"
        assert by_id["s"]["transport"] == "ssh"
        assert by_id["l"]["transport"] == "local"

    def test_list_peers_empty(self):
        mgr = PeerManager()
        assert mgr.list_peers() == []
