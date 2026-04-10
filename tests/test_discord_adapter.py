"""
Tests for DiscordAdapter (head/platform/discord_adapter.py).

Covers: properties, send_message rate limiting, init dedup via engine,
typing timeout, heartbeat MessageHandle type, and empty chunk handling.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from pathlib import Path

from head.config import Config, BotConfig, DiscordConfig
from head.platform.protocol import MessageHandle, FileAttachment
from head.platform.discord_adapter import (
    DiscordAdapter,
    HEARTBEAT_INTERVAL,
    TYPING_MAX_DURATION,
)


# ─── Helpers ───


def make_discord_config(**overrides) -> DiscordConfig:
    defaults = dict(
        token="test-token-123",
        allowed_channels=[],
        command_prefix="/",
        admin_users=[],
    )
    defaults.update(overrides)
    return DiscordConfig(**defaults)


def make_config(**discord_overrides) -> Config:
    discord_cfg = make_discord_config(**discord_overrides)
    return Config(bot=BotConfig(discord=discord_cfg))


def make_adapter(**discord_overrides) -> DiscordAdapter:
    """Create a DiscordAdapter with discord.py internals mocked."""
    with patch("head.platform.discord_adapter.commands.Bot"):
        adapter = DiscordAdapter(make_config(**discord_overrides))
    adapter.bot = MagicMock()
    return adapter


def make_mock_channel(channel_id: str = "discord:123"):
    """Create a mock Discord channel."""
    channel = AsyncMock()
    msg = MagicMock()
    msg.id = 99999
    channel.send = AsyncMock(return_value=msg)
    channel.typing = AsyncMock()
    return channel


# ─── Tests: Properties & Capabilities ───


class TestDiscordAdapterProperties:
    def test_platform_name(self):
        adapter = make_adapter()
        assert adapter.platform_name == "discord"

    def test_max_message_length(self):
        adapter = make_adapter()
        assert adapter.max_message_length == 2000

    def test_supports_message_edit(self):
        adapter = make_adapter()
        assert adapter.supports_message_edit() is True

    def test_supports_inline_buttons(self):
        adapter = make_adapter()
        assert adapter.supports_inline_buttons() is True

    def test_supports_file_upload(self):
        adapter = make_adapter()
        assert adapter.supports_file_upload() is True


# ─── Tests: send_message ───


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_short_message(self):
        adapter = make_adapter()
        channel = make_mock_channel()
        adapter._channels["discord:123"] = channel

        handle = await adapter.send_message("discord:123", "Hello world")
        channel.send.assert_called_once_with("Hello world")
        assert handle.platform == "discord"
        assert handle.channel_id == "discord:123"

    @pytest.mark.asyncio
    async def test_send_returns_message_handle(self):
        adapter = make_adapter()
        channel = make_mock_channel()
        adapter._channels["discord:123"] = channel

        handle = await adapter.send_message("discord:123", "test")
        assert isinstance(handle, MessageHandle)
        assert handle.message_id != "0"

    @pytest.mark.asyncio
    async def test_send_unknown_channel_returns_zero_id(self):
        adapter = make_adapter()
        handle = await adapter.send_message("discord:unknown", "test")
        assert handle.message_id == "0"

    @pytest.mark.asyncio
    async def test_send_long_message_splits_with_delay(self):
        """Verify that multi-chunk messages have delays between sends."""
        adapter = make_adapter()
        channel = make_mock_channel()
        adapter._channels["discord:123"] = channel

        # Create text longer than 2000 chars
        long_text = "A" * 2500

        sleep_calls = []
        original_sleep = asyncio.sleep

        async def mock_sleep(duration):
            sleep_calls.append(duration)

        with patch("head.platform.discord_adapter.asyncio.sleep", side_effect=mock_sleep):
            await adapter.send_message("discord:123", long_text)

        # Should have been split into 2 chunks, with a delay between them
        assert channel.send.call_count == 2
        assert len(sleep_calls) >= 1
        assert sleep_calls[0] == 0.3

    @pytest.mark.asyncio
    async def test_send_empty_chunks_returns_zero_handle(self):
        """When split_message returns empty list, should return zero handle."""
        adapter = make_adapter()
        channel = make_mock_channel()
        adapter._channels["discord:123"] = channel

        with patch("head.platform.discord_adapter.split_message", return_value=[]):
            handle = await adapter.send_message("discord:123", "   ")

        assert handle.message_id == "0"
        channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_deferred_interaction_consumed(self):
        """If a deferred interaction exists, followup.send is used instead."""
        adapter = make_adapter()
        interaction = MagicMock()
        msg = MagicMock()
        msg.id = 42
        interaction.followup.send = AsyncMock(return_value=msg)

        adapter._deferred_interactions["discord:123"] = interaction

        handle = await adapter.send_message("discord:123", "response")
        interaction.followup.send.assert_called_once_with("response", wait=True)
        assert handle.message_id == "42"
        # Interaction should be consumed
        assert "discord:123" not in adapter._deferred_interactions


# ─── Tests: edit_message ───


class TestEditMessage:
    @pytest.mark.asyncio
    async def test_edit_existing_message(self):
        import discord as _discord

        adapter = make_adapter()
        raw_msg = AsyncMock(spec=_discord.Message)
        handle = MessageHandle(
            platform="discord",
            channel_id="discord:123",
            message_id="1",
            raw=raw_msg,
        )
        await adapter.edit_message(handle, "updated")
        raw_msg.edit.assert_called_once_with(content="updated")

    @pytest.mark.asyncio
    async def test_edit_truncates_long_text(self):
        import discord as _discord

        adapter = make_adapter()
        raw_msg = AsyncMock(spec=_discord.Message)
        handle = MessageHandle(
            platform="discord",
            channel_id="discord:123",
            message_id="1",
            raw=raw_msg,
        )
        long_text = "X" * 3000
        await adapter.edit_message(handle, long_text)
        call_args = raw_msg.edit.call_args
        assert len(call_args.kwargs["content"]) <= 2000

    @pytest.mark.asyncio
    async def test_edit_no_raw_message_noop(self):
        adapter = make_adapter()
        handle = MessageHandle(
            platform="discord",
            channel_id="discord:123",
            message_id="1",
            raw=None,
        )
        # Should not raise
        await adapter.edit_message(handle, "updated")


# ─── Tests: Init message deduplication ───


class TestInitDedup:
    def test_no_adapter_level_init_shown(self):
        """After fix, adapter should NOT have its own _init_shown set."""
        adapter = make_adapter()
        assert not hasattr(adapter, "_init_shown")


# ─── Tests: Heartbeat message type ───


class TestHeartbeatMsgType:
    def test_heartbeat_msgs_accepts_message_handle(self):
        """_heartbeat_msgs should store MessageHandle, not raw discord.Message."""
        adapter = make_adapter()
        handle = MessageHandle(
            platform="discord",
            channel_id="discord:123",
            message_id="1",
        )
        adapter._heartbeat_msgs["discord:123"] = handle
        assert isinstance(adapter._heartbeat_msgs["discord:123"], MessageHandle)


# ─── Tests: Typing indicator ───


class TestTypingIndicator:
    @pytest.mark.asyncio
    async def test_start_stop_typing(self):
        adapter = make_adapter()
        channel = make_mock_channel()
        adapter._channels["discord:123"] = channel

        await adapter.start_typing("discord:123")
        assert "discord:123" in adapter._typing_tasks

        await adapter.stop_typing("discord:123")
        assert "discord:123" not in adapter._typing_tasks

    @pytest.mark.asyncio
    async def test_stop_typing_no_task(self):
        """Stopping typing on a channel with no task should not raise."""
        adapter = make_adapter()
        await adapter.stop_typing("discord:999")

    def test_typing_max_duration_constant(self):
        """TYPING_MAX_DURATION should be 24 hours (86400 seconds)."""
        assert TYPING_MAX_DURATION == 86400


# ─── Tests: delete_message ───


class TestDeleteMessage:
    @pytest.mark.asyncio
    async def test_delete_message(self):
        import discord as _discord

        adapter = make_adapter()
        raw_msg = AsyncMock(spec=_discord.Message)
        handle = MessageHandle(
            platform="discord",
            channel_id="discord:123",
            message_id="1",
            raw=raw_msg,
        )
        await adapter.delete_message(handle)
        raw_msg.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_no_raw_noop(self):
        adapter = make_adapter()
        handle = MessageHandle(
            platform="discord",
            channel_id="discord:123",
            message_id="1",
            raw=None,
        )
        await adapter.delete_message(handle)


# ─── Tests: Streaming flag ───


class TestStreamingFlag:
    def test_streaming_set_initial_empty(self):
        adapter = make_adapter()
        assert len(adapter._streaming) == 0
