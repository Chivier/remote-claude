"""Direct HTTPS transport with Bearer token authentication."""

import ssl
from typing import Optional

import aiohttp

from head.transport import Transport


class HTTPTransport(Transport):
    """Transport that connects to a daemon over HTTPS with token auth.

    Designed for direct connections where the daemon exposes an HTTPS
    endpoint (e.g., with a self-signed certificate). Authentication is
    via a Bearer token in the Authorization header.
    """

    def __init__(
        self,
        peer_id: str,
        address: str,
        token: str,
        tls_fingerprint: Optional[str] = None,
        verify_tls: bool = False,
    ) -> None:
        self._peer_id = peer_id
        self._address = address
        self._token = token
        self._tls_fingerprint = tls_fingerprint
        self._verify_tls = verify_tls
        self._connected = False
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def peer_id(self) -> str:
        return self._peer_id

    def get_base_url(self) -> str:
        return f"https://{self._address}"

    def get_auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def is_alive(self) -> bool:
        return self._connected and self._session is not None and not self._session.closed

    async def connect(self) -> None:
        """Create an aiohttp ClientSession with appropriate SSL settings."""
        if self._verify_tls:
            ssl_context = ssl.create_default_context()
        else:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        connector = aiohttp.TCPConnector(ssl=ssl_context)
        self._session = aiohttp.ClientSession(connector=connector)
        self._connected = True

    async def close(self) -> None:
        """Close the underlying aiohttp session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._connected = False
        self._session = None
