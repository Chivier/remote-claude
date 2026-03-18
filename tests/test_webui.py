"""Tests for the Codecast WebUI server."""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from head.webui.server import create_app


@pytest.fixture
async def client():
    app = await create_app()
    async with TestClient(TestServer(app)) as c:
        yield c


@pytest.mark.asyncio
async def test_dashboard_returns_200(client):
    resp = await client.get("/")
    assert resp.status == 200
    text = await resp.text()
    assert "Codecast" in text
    assert "Dashboard" in text


@pytest.mark.asyncio
async def test_peers_page_returns_200(client):
    resp = await client.get("/peers")
    assert resp.status == 200
    text = await resp.text()
    assert "Peers" in text


@pytest.mark.asyncio
async def test_sessions_page_returns_200(client):
    resp = await client.get("/sessions")
    assert resp.status == 200
    text = await resp.text()
    assert "Sessions" in text


@pytest.mark.asyncio
async def test_settings_page_returns_200(client):
    resp = await client.get("/settings")
    assert resp.status == 200
    text = await resp.text()
    assert "Settings" in text


@pytest.mark.asyncio
async def test_api_status_returns_html(client):
    resp = await client.get("/api/status")
    assert resp.status == 200
    assert "text/html" in resp.content_type
    text = await resp.text()
    assert "status-grid" in text


@pytest.mark.asyncio
async def test_api_peers_returns_html(client):
    resp = await client.get("/api/peers")
    assert resp.status == 200
    assert "text/html" in resp.content_type


@pytest.mark.asyncio
async def test_static_css_served(client):
    resp = await client.get("/static/style.css")
    assert resp.status == 200
    text = await resp.text()
    assert "--bg" in text


@pytest.mark.asyncio
async def test_login_page_returns_200(client):
    resp = await client.get("/login")
    assert resp.status == 200
    text = await resp.text()
    assert "Login" in text


@pytest.mark.asyncio
async def test_dashboard_with_config():
    """Test dashboard renders correctly with a real config object."""
    from head.config import Config, PeerConfig

    config = Config()
    config.peers = {
        "test-peer": PeerConfig(id="test-peer", transport="ssh", ssh_host="10.0.0.1"),
    }

    app = await create_app(config)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/")
        assert resp.status == 200
        text = await resp.text()
        assert "1" in text  # peer_count

        # Check API returns peer info
        resp = await client.get("/api/peers")
        text = await resp.text()
        assert "test-peer" in text
        assert "10.0.0.1" in text


@pytest.mark.asyncio
async def test_api_status_with_config():
    """Test status API includes peer count from config."""
    from head.config import Config, PeerConfig

    config = Config()
    config.peers = {
        "a": PeerConfig(id="a"),
        "b": PeerConfig(id="b"),
    }

    app = await create_app(config)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/api/status")
        text = await resp.text()
        assert "2" in text  # two peers


@pytest.mark.asyncio
async def test_auth_not_required_localhost():
    """When bind is 127.0.0.1, all pages are accessible without auth."""
    app = await create_app(bind="127.0.0.1")
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/")
        assert resp.status == 200


@pytest.mark.asyncio
async def test_auth_required_remote_bind():
    """When bind is 0.0.0.0, non-login pages redirect to /login."""
    app = await create_app(bind="0.0.0.0")
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/", allow_redirects=False)
        assert resp.status == 302
        assert "/login" in resp.headers.get("Location", "")


@pytest.mark.asyncio
async def test_auth_allows_static_without_login():
    """Static files should be accessible even when auth is required."""
    app = await create_app(bind="0.0.0.0")
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/static/style.css")
        assert resp.status == 200
