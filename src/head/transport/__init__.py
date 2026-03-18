"""Transport protocol abstraction for daemon communication."""

from abc import ABC, abstractmethod


class Transport(ABC):
    """Abstract base class for transport protocols.

    A Transport encapsulates how the head node connects to and communicates
    with a remote daemon. Implementations handle connection setup, URL
    generation, authentication headers, and lifecycle management.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish the transport connection."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Tear down the transport connection and release resources."""
        ...

    @abstractmethod
    def get_base_url(self) -> str:
        """Return the base URL for JSON-RPC requests to the daemon."""
        ...

    @abstractmethod
    def is_alive(self) -> bool:
        """Return True if the transport connection is active and usable."""
        ...

    @abstractmethod
    def get_auth_headers(self) -> dict[str, str]:
        """Return authentication headers to include in requests."""
        ...

    @property
    @abstractmethod
    def peer_id(self) -> str:
        """Return the identifier for the remote peer."""
        ...
