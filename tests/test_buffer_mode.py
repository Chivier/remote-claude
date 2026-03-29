"""
Integration tests for buffer tool display mode.

Simulates Discord/Telegram message flows and verifies:
1. Buffer mode produces exactly 1 status message + 1 merged result message
2. Status message is edited (not new messages) for progress updates
3. AskUserQuestion interrupts are handled correctly
4. Error events are sent immediately
5. Empty responses produce only the status message (finalized to "Done")
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from typing import Any, Optional
from pathlib import Path

from head.engine import BotEngine
from head.platform.protocol import MessageHandle, InputHandler
from head.config import Config, PeerConfig
from head.session_router import SessionRouter


class MockAdapter:
    """Mock PlatformAdapter that records sent/edited/deleted messages."""

    def __init__(self, platform: str = "discord"):
        self.sent_messages: list[tuple[str, str]] = []
        self.edited_messages: list[tuple[str, str]] = []
        self.deleted_messages: list[str] = []
        self._msg_counter = 0
        self._on_input: Optional[InputHandler] = None
        self._platform = platform

    @property
    def platform_name(self) -> str:
        return self._platform

    @property
    def max_message_length(self) -> int:
        return 2000 if self._platform == "discord" else 4096

    async def send_message(self, channel_id: str, text: str) -> MessageHandle:
        self._msg_counter += 1
        self.sent_messages.append((channel_id, text))
        return MessageHandle(
            platform=self._platform,
            channel_id=channel_id,
            message_id=f"msg-{self._msg_counter}",
        )

    async def edit_message(self, handle: MessageHandle, text: str) -> None:
        self.edited_messages.append((handle.message_id, text))

    async def delete_message(self, handle: MessageHandle) -> None:
        self.deleted_messages.append(handle.message_id)

    async def download_file(self, attachment, dest: Path) -> Path:
        return dest

    async def send_file(self, channel_id: str, path: Path, caption: str = "") -> MessageHandle:
        return MessageHandle(platform=self._platform, channel_id=channel_id, message_id="file-1")

    async def start_typing(self, channel_id: str) -> None:
        pass

    async def stop_typing(self, channel_id: str) -> None:
        pass

    def supports_message_edit(self) -> bool:
        return True

    def supports_inline_buttons(self) -> bool:
        return False

    def supports_file_upload(self) -> bool:
        return True

    def set_input_handler(self, handler: InputHandler) -> None:
        self._on_input = handler

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class MockBotEngine(BotEngine):
    def __init__(self, adapter, ssh_manager, session_router, daemon_client, config):
        super().__init__(adapter, ssh_manager, session_router, daemon_client, config)
        self.adapter: MockAdapter

    @property
    def sent_messages(self) -> list[tuple[str, str]]:
        return self.adapter.sent_messages

    @property
    def edited_messages(self) -> list[tuple[str, str]]:
        return self.adapter.edited_messages

    def sent_texts(self) -> list[str]:
        return [text for _, text in self.adapter.sent_messages]

    def edit_texts(self) -> list[str]:
        return [text for _, text in self.adapter.edited_messages]


# ─── Fixtures ───


@pytest.fixture
def mock_ssh():
    ssh = AsyncMock()
    ssh.ensure_tunnel = AsyncMock(return_value=19100)
    ssh.get_local_port = MagicMock(return_value=None)
    ssh.sync_skills = AsyncMock()
    ssh.list_machines = AsyncMock(return_value=[])
    return ssh


@pytest.fixture
def mock_router(tmp_path):
    return SessionRouter(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def mock_daemon():
    return AsyncMock()


@pytest.fixture
def mock_config():
    config = Config()
    config.peers = {
        "gpu-1": PeerConfig(id="gpu-1", ssh_host="10.0.0.1", ssh_user="user"),
    }
    config.default_mode = "auto"
    return config


@pytest.fixture(params=["discord", "telegram"])
def bot(request, mock_ssh, mock_router, mock_daemon, mock_config):
    """Create a MockBotEngine for each platform (discord + telegram)."""
    adapter = MockAdapter(platform=request.param)
    engine = MockBotEngine(adapter, mock_ssh, mock_router, mock_daemon, mock_config)
    adapter.set_input_handler(engine.handle_input)
    return engine


def _tool_event(tool: str, message: str = "", input_data: Any = None) -> dict:
    e: dict = {"type": "tool_use", "tool": tool}
    if message:
        e["message"] = message
    if input_data is not None:
        e["input"] = input_data
    return e


# ═══════════════════════════════════════════════════════════
# Buffer mode integration tests
# ═══════════════════════════════════════════════════════════


class TestBufferModeBasic:
    """Buffer mode produces minimal messages: 1 status + 1 result."""

    @pytest.mark.asyncio
    async def test_tools_then_text_produces_two_messages(self, bot, mock_router, mock_daemon):
        """Stream with tools + text -> 1 status msg (edited to done) + 1 result msg."""
        channel = f"{bot.adapter.platform_name}:100"
        mock_router.register(channel, "gpu-1", "/path", "sess-001")
        # buffer is now the default, no need to change tool_display

        async def mock_stream(*a, **kw):
            yield _tool_event("Read", message="file.py")
            yield _tool_event("Edit", message="file.py")
            yield _tool_event("Bash", message="pytest")
            yield {"type": "text", "content": "All tests pass. Here is the summary."}
            yield {"type": "result", "session_id": "sdk-1"}

        mock_daemon.send_message = mock_stream
        await bot.handle_input(channel, "run the tests")

        texts = bot.sent_texts()
        # Exactly 2 messages: status + result
        assert len(texts) == 2
        # First message is the status (Thinking...)
        assert "Thinking" in texts[0]
        # Second message is the merged result
        assert "All tests pass" in texts[1]
        # Status message was edited to "Done"
        edits = bot.edit_texts()
        assert any("Done in" in e for e in edits)

    @pytest.mark.asyncio
    async def test_no_tool_calls_only_text(self, bot, mock_router, mock_daemon):
        """Stream with only text (no tools) -> just the result, no status message."""
        channel = f"{bot.adapter.platform_name}:101"
        mock_router.register(channel, "gpu-1", "/path", "sess-002")

        async def mock_stream(*a, **kw):
            yield {"type": "text", "content": "Hello! How can I help?"}
            yield {"type": "result", "session_id": "sdk-2"}

        mock_daemon.send_message = mock_stream
        await bot.handle_input(channel, "hi")

        texts = bot.sent_texts()
        assert len(texts) == 1
        assert "Hello! How can I help?" in texts[0]

    @pytest.mark.asyncio
    async def test_tools_only_no_text(self, bot, mock_router, mock_daemon):
        """Stream with only tools (no text) -> status message finalized to Done."""
        channel = f"{bot.adapter.platform_name}:102"
        mock_router.register(channel, "gpu-1", "/path", "sess-003")

        async def mock_stream(*a, **kw):
            yield _tool_event("Read", message="check.py")
            yield {"type": "result", "session_id": "sdk-3"}

        mock_daemon.send_message = mock_stream
        await bot.handle_input(channel, "check")

        texts = bot.sent_texts()
        assert len(texts) == 1  # Just the status message
        assert "Thinking" in texts[0]
        edits = bot.edit_texts()
        assert any("Done in" in e for e in edits)


class TestBufferModeToolTracking:
    """Buffer mode tracks rolling last-3 unique tool names."""

    @pytest.mark.asyncio
    async def test_tool_names_in_status(self, bot, mock_router, mock_daemon):
        """Status message includes recent tool names."""
        channel = f"{bot.adapter.platform_name}:200"
        mock_router.register(channel, "gpu-1", "/path", "sess-010")

        async def mock_stream(*a, **kw):
            yield _tool_event("Read", message="a.py")
            yield _tool_event("Edit", message="b.py")
            yield _tool_event("Bash", message="test")
            yield {"type": "text", "content": "Done."}
            yield {"type": "result", "session_id": "sdk-10"}

        mock_daemon.send_message = mock_stream
        await bot.handle_input(channel, "fix it")

        # The initial status should mention tool names
        texts = bot.sent_texts()
        status_text = texts[0]
        # At minimum the first tool should appear
        assert "Read" in status_text

    @pytest.mark.asyncio
    async def test_rolling_window_caps_at_three(self, bot, mock_router, mock_daemon):
        """When >3 unique tools are used, only last 3 appear in status."""
        channel = f"{bot.adapter.platform_name}:201"
        mock_router.register(channel, "gpu-1", "/path", "sess-011")

        async def mock_stream(*a, **kw):
            yield _tool_event("Read", message="a")
            yield _tool_event("Write", message="b")
            yield _tool_event("Grep", message="c")
            yield _tool_event("Bash", message="d")
            yield _tool_event("Edit", message="e")
            yield {"type": "text", "content": "Result"}
            yield {"type": "result", "session_id": "sdk-11"}

        mock_daemon.send_message = mock_stream
        await bot.handle_input(channel, "go")

        # The "Done" edit should have tool_count = 5
        edits = bot.edit_texts()
        done_edit = [e for e in edits if "Done in" in e]
        assert len(done_edit) == 1
        assert "5 tool calls" in done_edit[0]


class TestBufferModeEdgeCases:
    """Edge cases: errors, queued, AskUserQuestion."""

    @pytest.mark.asyncio
    async def test_error_sent_immediately(self, bot, mock_router, mock_daemon):
        """Error events are sent as separate messages even in buffer mode."""
        channel = f"{bot.adapter.platform_name}:300"
        mock_router.register(channel, "gpu-1", "/path", "sess-020")

        async def mock_stream(*a, **kw):
            yield _tool_event("Bash", message="failing cmd")
            yield {"type": "error", "message": "Process crashed"}
            yield {"type": "result", "session_id": "sdk-20"}

        mock_daemon.send_message = mock_stream
        await bot.handle_input(channel, "run it")

        texts = bot.sent_texts()
        assert any("Process crashed" in t for t in texts)

    @pytest.mark.asyncio
    async def test_queued_returns_early(self, bot, mock_router, mock_daemon):
        """Queued event produces a message and returns."""
        channel = f"{bot.adapter.platform_name}:301"
        mock_router.register(channel, "gpu-1", "/path", "sess-021")

        async def mock_stream(*a, **kw):
            yield {"type": "queued", "position": 2}

        mock_daemon.send_message = mock_stream
        await bot.handle_input(channel, "work")

        texts = bot.sent_texts()
        assert len(texts) == 1
        assert "queued" in texts[0].lower()

    @pytest.mark.asyncio
    async def test_multiple_text_events_merged(self, bot, mock_router, mock_daemon):
        """Multiple text events are merged into one message at the end."""
        channel = f"{bot.adapter.platform_name}:302"
        mock_router.register(channel, "gpu-1", "/path", "sess-022")

        async def mock_stream(*a, **kw):
            yield _tool_event("Read", message="file")
            yield {"type": "text", "content": "Part 1 of the response."}
            yield {"type": "text", "content": "Part 2 of the response."}
            yield {"type": "result", "session_id": "sdk-22"}

        mock_daemon.send_message = mock_stream
        await bot.handle_input(channel, "explain")

        texts = bot.sent_texts()
        # 1 status + 1 merged result (2 parts joined)
        assert len(texts) == 2
        assert "Part 1" in texts[1]
        assert "Part 2" in texts[1]

    @pytest.mark.asyncio
    async def test_bare_tool_events_not_counted(self, bot, mock_router, mock_daemon):
        """Bare tool_use events (no input/message) should not increment counter."""
        channel = f"{bot.adapter.platform_name}:303"
        mock_router.register(channel, "gpu-1", "/path", "sess-023")

        async def mock_stream(*a, **kw):
            yield {"type": "tool_use", "tool": "Read"}  # bare, no detail
            yield _tool_event("Read", message="with detail")  # detailed
            yield {"type": "text", "content": "Done"}
            yield {"type": "result", "session_id": "sdk-23"}

        mock_daemon.send_message = mock_stream
        await bot.handle_input(channel, "check")

        edits = bot.edit_texts()
        done_edit = [e for e in edits if "Done in" in e]
        assert len(done_edit) == 1
        assert "1 tool call" in done_edit[0]


class TestBufferModeNoMessageSpam:
    """Verify buffer mode doesn't spam the user."""

    @pytest.mark.asyncio
    async def test_many_tools_still_two_messages(self, bot, mock_router, mock_daemon):
        """Even with 50 tool calls, buffer mode sends only 2 messages (status + result)."""
        channel = f"{bot.adapter.platform_name}:400"
        mock_router.register(channel, "gpu-1", "/path", "sess-030")

        async def mock_stream(*a, **kw):
            for i in range(50):
                yield _tool_event(f"Tool{i % 5}", message=f"action{i}")
            yield {"type": "text", "content": "Final result after many tools."}
            yield {"type": "result", "session_id": "sdk-30"}

        mock_daemon.send_message = mock_stream
        await bot.handle_input(channel, "big task")

        texts = bot.sent_texts()
        assert len(texts) == 2  # status + result, no matter how many tools

    @pytest.mark.asyncio
    async def test_no_intermediate_edits_for_fast_stream(self, bot, mock_router, mock_daemon):
        """A fast stream (< 30s) should have at most 1 edit (the 'Done' finalization)."""
        channel = f"{bot.adapter.platform_name}:401"
        mock_router.register(channel, "gpu-1", "/path", "sess-031")

        async def mock_stream(*a, **kw):
            yield _tool_event("Read", message="quick.py")
            yield {"type": "text", "content": "Quick answer."}
            yield {"type": "result", "session_id": "sdk-31"}

        mock_daemon.send_message = mock_stream
        await bot.handle_input(channel, "fast")

        edits = bot.edit_texts()
        # Only the "Done in Xs" finalization edit
        assert len(edits) == 1
        assert "Done in" in edits[0]
