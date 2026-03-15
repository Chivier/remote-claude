# Multi-Platform Adapter Architecture Design

**Date:** 2026-03-15  
**Status:** Approved  
**Scope:** Refactor bot abstraction layer + full Telegram feature parity + extensibility for Lark

## Problem

The current architecture has Discord as a first-class citizen with full features (file transfer, heartbeat, slash commands, typing indicators), while Telegram is a thin wrapper with basic text-only support. The codebase has platform-specific logic scattered across `bot_base.py` (which is an ABC) and `bot_discord.py`/`bot_telegram.py` (which inherit it). Adding a third platform (Lark/Feishu) would require duplicating significant amounts of streaming, heartbeat, and file handling logic.

### Current Feature Gap

| Feature | Discord | Telegram |
|---------|---------|----------|
| File transfer | FilePool + SCP upload | Not supported |
| Streaming heartbeat | 25s heartbeat + typing indicator | None |
| Rich interaction | Slash commands + autocomplete | Basic CommandHandler |
| Admin check | `admin_users` (Discord ID); `is_admin()` exclusively checks Discord config | No admin support at all (`is_admin` always returns False for Telegram) |
| Restart notification | Supported (resolves channel by Discord ID) | Not supported (channel prefix mismatch) |
| Streaming response | Dedicated `_forward_message_with_heartbeat` | Reuses base `_forward_message` (no heartbeat) |
| Group chat support | Channel-based with `allowed_channels` | No group filtering; no `@botname` command handling |

## Approach: Protocol + Adapter Pattern

Define a `PlatformAdapter` protocol that each chat platform implements. Replace the current `BotBase` ABC inheritance with a `BotEngine` concrete class that holds an adapter instance via composition. All command logic, streaming, and file handling live in the engine; adapters only handle platform-specific I/O.

### Why This Approach

- **Separation of concerns**: Platform-specific code is isolated in adapters; business logic lives in one place (engine).
- **Testability**: Engine can be tested with a mock adapter.
- **Extensibility**: Adding Lark means writing one adapter file, not touching the engine.
- **No diamond inheritance**: Avoids mixin complexity that would grow with each new platform.

Alternatives considered and rejected:
- **Mixin inheritance**: Minimal change but fragile; diamond inheritance problems with 3+ platforms.
- **Event bus**: Over-engineered for this project's scale; adds debugging complexity.

## Design

### Module 1: PlatformAdapter Protocol

File: `head/platform/protocol.py`

```python
from typing import Protocol, Any, Optional, runtime_checkable, AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MessageHandle:
    """Platform-agnostic message handle for subsequent edit/delete."""
    platform: str           # "discord", "telegram", "lark"
    channel_id: str         # Unified channel ID (includes platform prefix)
    message_id: str         # Platform-native message ID (stringified)
    raw: Any = None         # Platform-native message object (needed for edit/delete)


@dataclass
class FileAttachment:
    """Platform-agnostic file attachment descriptor."""
    filename: str           # Original filename
    size: int               # File size in bytes (0 if unknown)
    mime_type: Optional[str]  # MIME type
    url: Optional[str]      # Direct download URL (Discord has, Telegram doesn't)
    platform_ref: Any       # Platform-native reference (Discord Attachment / Telegram File)


@runtime_checkable
class PlatformAdapter(Protocol):
    """Interface that each chat platform must implement."""

    @property
    def platform_name(self) -> str: ...        # "discord" / "telegram" / "lark"

    @property
    def max_message_length(self) -> int: ...    # 2000 / 4096 / 4000

    # --- Message Operations ---
    async def send_message(self, channel_id: str, text: str) -> MessageHandle: ...
    async def edit_message(self, handle: MessageHandle, text: str) -> None: ...
    async def delete_message(self, handle: MessageHandle) -> None: ...

    # --- File Operations ---
    async def download_file(self, attachment: FileAttachment, dest: Path) -> Path: ...
    async def send_file(self, channel_id: str, path: Path, caption: str = "") -> MessageHandle: ...

    # --- Interaction State ---
    async def start_typing(self, channel_id: str) -> None: ...
    async def stop_typing(self, channel_id: str) -> None: ...

    # --- Capability Queries ---
    def supports_message_edit(self) -> bool: ...
    def supports_inline_buttons(self) -> bool: ...
    def supports_file_upload(self) -> bool: ...

    # --- Input Callback ---
    def set_input_handler(self, handler: InputHandler) -> None: ...

    # --- Lifecycle ---
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


# Type alias for the input handler callback
InputHandler = Callable[
    [str, str, Optional[int], Optional[list[FileAttachment]]],
    Coroutine[Any, Any, None],
]
```

**Design decisions:**

1. `MessageHandle` encapsulates platform differences — Discord uses `handle.raw` (a `discord.Message` object) for edits; Telegram uses `handle.channel_id` + `handle.message_id` (parsed back to `chat_id` + `message_id` integers). Each adapter's `edit_message` implementation reads whichever fields it needs from the handle.
2. `FileAttachment` uniformly describes attachments; `download_file` is implemented by each adapter with platform-specific download logic.
3. Capability query methods let the engine degrade gracefully (e.g., send new message if platform doesn't support edit).
4. `set_input_handler` is part of the protocol. Adapters store the callback and invoke it when receiving user messages: `await self._on_input(channel_id, text, user_id, attachments)`. This is the sole coupling point between adapter and engine — adapters never import or reference `BotEngine` directly.

### Module 2: BotEngine (replaces BotBase)

File: `head/engine.py`

The engine is a concrete class, not abstract. It holds a `PlatformAdapter` instance and contains all command logic and streaming.

```python
class BotEngine:
    """Platform-agnostic command engine. All command logic and streaming live here."""

    def __init__(
        self,
        adapter: PlatformAdapter,
        ssh_manager: SSHManager,
        session_router: SessionRouter,
        daemon_client: DaemonClient,
        config: Config,
        file_pool: Optional[FilePool] = None,
    ):
        self.adapter = adapter
        self.ssh = ssh_manager
        self.router = session_router
        self.daemon = daemon_client
        self.config = config
        self.file_pool = file_pool
        self._streaming: set[str] = set()
```

**Key changes from BotBase:**

1. All `self.send_message(...)` → `self.adapter.send_message(...)`; returns `MessageHandle` instead of platform-native object.
2. All `self.edit_message(...)` → `self.adapter.edit_message(handle, text)`.
3. Message splitting uses `self.adapter.max_message_length` instead of hardcoded 2000/4096.
4. Streaming forwarding (`_forward_message`) is unified with typing indicator and heartbeat for all platforms, with capability-based degradation.

#### Unified Streaming

The Discord-specific `_forward_message_with_heartbeat` and the base `_forward_message` merge into one:

```python
async def _forward_message(self, channel_id: str, text: str,
                            file_refs: list[FileEntry] | None = None):
    """Unified streaming forward with typing and heartbeat for all platforms."""

    # 1. Typing indicator (all platforms)
    await self.adapter.start_typing(channel_id)

    # 2. Heartbeat (all platforms, presentation differs)
    heartbeat_task = asyncio.create_task(
        self._heartbeat_loop(channel_id, time.time(), event_tracker)
    )

    # 3. Streaming display (strategy based on supports_message_edit)
    if self.adapter.supports_message_edit():
        # Edit same message with cursor (Discord, Telegram both support this)
        ...
    else:
        # Send new messages (degraded mode for platforms without edit)
        ...
```

#### Unified handle_input

Extended signature with `attachments` parameter:

```python
async def handle_input(
    self,
    channel_id: str,
    text: str,
    user_id: Optional[int] = None,
    attachments: list[FileAttachment] | None = None,
) -> None:
```

#### Unified Admin Check

Admin check routes to the correct platform config based on `adapter.platform_name`. For extensibility, a registry pattern can be used if the hardcoded platform names become unwieldy, but for 2-3 platforms the explicit approach is clearer:

```python
def is_admin(self, user_id: Optional[int]) -> bool:
    platform = self.adapter.platform_name
    if platform == "discord" and self.config.bot.discord:
        return user_id in (self.config.bot.discord.admin_users or [])
    if platform == "telegram" and self.config.bot.telegram:
        return user_id in (self.config.bot.telegram.admin_users or [])
    return False
```

#### Restart Notification

`check_restart_notify` reads a file containing `channel_id` (e.g., `discord:123456`) and sends a message. In the new architecture, each engine's `check_restart_notify` checks if the stored channel_id prefix matches its adapter's platform. Only the matching engine sends the notification:

```python
async def check_restart_notify(self) -> None:
    restart_file = Path.cwd() / ".restart_notify"
    if not restart_file.exists():
        return
    content = restart_file.read_text().strip().splitlines()
    if len(content) >= 2:
        channel_id = content[0]
        # Only handle if this channel belongs to our platform
        if not channel_id.startswith(f"{self.adapter.platform_name}:"):
            return
        restart_file.unlink()
        await self.adapter.send_message(channel_id, f"**{content[1]} complete.** Head node is back online.")
```

#### Interactive State Management

The engine stores interactive flow state (`_ssh_import_entries`, `_ssh_import_channel`, `_remove_confirm_machine`, `_remove_confirm_channel`, etc.) as instance attributes, same as current `BotBase`. Since each platform gets its own `BotEngine` instance, there is no cross-platform state collision. However, all engines share the same `SessionRouter` and `SSHManager` — these are already async-safe (SQLite uses per-call connections; SSH manager uses asyncio locks).

#### Init Message Deduplication

The engine tracks `_init_shown: set[str]` (keyed by `daemon_session_id`) to avoid showing "Connected to **model**" multiple times for the same session. This is the Discord bot's current behavior; the base `_forward_message` shows it every time. The unified engine adopts the deduplication behavior.

#### File Reference Markers

The current codebase uses `<discord_file>{file_id}</discord_file>` markers in message text. These are renamed to the platform-agnostic `<file_ref>{file_id}</file_ref>`. This affects:
- `engine.py` (replaces markers with remote paths after SCP upload)
- Each adapter (appends markers when processing incoming attachments)

### Module 3: FilePool Generalization

File: `head/file_pool.py` (modified)

**Retained responsibilities** (unchanged):
- Local file cache directory management
- LRU eviction strategy
- MIME type allowlist validation
- Filename sanitization
- `FileEntry` data structure

**New generic methods:**

```python
class FilePool:
    async def store_file(
        self,
        data: bytes,
        original_name: str,
        mime_type: str,
        session_prefix: str = "",
    ) -> FileEntry:
        """Generic entry point: receive raw bytes, store to pool, return FileEntry."""
        ...

    async def store_from_path(
        self,
        source: Path,
        original_name: str,
        mime_type: str,
        session_prefix: str = "",
    ) -> FileEntry:
        """Store from a local file path (move or copy into pool)."""
        ...
```

**Removed:** `download_discord_attachment` method. File download logic moves to each adapter's `download_file`.

**New file transfer flow:**

```
Platform attachment
  → Adapter.download_file(attachment, temp_path)
  → FilePool.store_from_path(temp_path, name, mime) → FileEntry
  → SSHManager.upload_files(machine_id, [entry]) → remote paths
  → Replace markers in message text
  → Send to daemon
```

### Module 4: TelegramAdapter

File: `head/platform/telegram_adapter.py`

#### Message Formatting

Switch from `ParseMode.MARKDOWN` (v1) to **HTML**:
- MarkdownV2 requires escaping `.`, `-`, `(`, `)`, etc. — error-prone with Claude's code output
- HTML `<pre>`, `<code>`, `<b>` tags are more compatible with Claude's markdown output

A `markdown_to_telegram_html()` conversion function handles the translation. Falls back to plain text on formatting errors.

#### Typing Indicator

Telegram's `send_chat_action(ChatAction.TYPING)` lasts ~5 seconds. Loop every 4 seconds (similar to Discord's approach):

```python
async def start_typing(self, channel_id: str):
    async def loop():
        while True:
            await self._bot.send_chat_action(chat_id, ChatAction.TYPING)
            await asyncio.sleep(4)
    self._typing_tasks[channel_id] = asyncio.create_task(loop())
```

#### Command Registration

Use `bot.set_my_commands()` to show command menu when user types `/`:

```python
commands = [
    BotCommand("start", "Start a new Claude session"),
    BotCommand("resume", "Resume a previous session"),
    BotCommand("ls", "List machines or sessions"),
    BotCommand("exit", "Detach from current session"),
    BotCommand("mode", "Switch permission mode"),
    BotCommand("status", "Show current session info"),
    BotCommand("interrupt", "Interrupt Claude"),
    BotCommand("rename", "Rename current session"),
    BotCommand("health", "Check daemon health"),
    BotCommand("monitor", "Monitor session details"),
    BotCommand("help", "Show available commands"),
]
```

#### File Handling

Telegram Bot API has a 20MB file size limit (regular bots). The adapter checks file size and reports errors for oversized files.

Supported attachment types:
- `message.document` — generic files
- `message.photo` — photos (take largest `PhotoSize`)
- `message.video` — videos
- `message.audio` — audio files
- `message.voice` — voice messages

#### Rate Limits and Edit Idempotency

Telegram Bot API has rate limits: ~30 messages/second globally, ~1 message/second per chat for edits. The streaming `STREAM_UPDATE_INTERVAL` of 1.5 seconds is safe for edits, but the adapter must handle:

- `telegram.error.BadRequest: Message is not modified` — occurs when `editMessageText` receives identical text (e.g., streaming delta only adds whitespace). The adapter catches this and silently ignores it.
- `telegram.error.RetryAfter` — rate limit exceeded. The adapter respects the `retry_after` value and delays.

```python
async def edit_message(self, handle: MessageHandle, text: str) -> None:
    try:
        await self._bot.edit_message_text(
            chat_id=..., message_id=..., text=text, parse_mode=ParseMode.HTML
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass  # Silently ignore identical content
        else:
            raise
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after)
        await self.edit_message(handle, text)  # Retry once
```

#### Group Chat Support

When `allowed_chats` is configured, the adapter supports group chats with these considerations:

1. **Bot username suffix**: In groups, commands arrive as `/start@MyClaudeBot`. The adapter strips the `@botname` suffix before dispatching to the engine.
2. **Privacy mode**: By default, bots in groups only receive commands (not regular messages). Users must either disable privacy mode via BotFather, or the adapter instructs users to always prefix messages with the bot mention.
3. **Channel ID**: Group chats use `telegram:{chat_id}` where `chat_id` is negative for groups/supergroups.

#### Deferred Interaction (Discord-specific adapter concern)

Discord's slash commands require `interaction.response.defer()` + `interaction.followup.send()`. This is handled entirely within `DiscordAdapter.send_message()` which checks for pending deferred interactions and uses followup if available. This pattern is invisible to the engine — it only sees `MessageHandle` returns. This is documented here for implementer awareness but requires no protocol-level changes.

#### Webhook Support (Future)

Keep polling as default. Config supports optional webhook for future production deployment:

```yaml
telegram:
  token: ${TELEGRAM_TOKEN}
  allowed_users: [123456]
  admin_users: [123456]
  # webhook:                    # Optional, future
  #   url: https://example.com/webhook
  #   port: 8443
```

### Module 5: Configuration Changes

#### TelegramConfig

```python
@dataclass
class TelegramConfig:
    token: str
    allowed_users: list[int] = field(default_factory=list)
    admin_users: list[int] = field(default_factory=list)      # NEW
    allowed_chats: list[int] = field(default_factory=list)     # NEW: group chat filtering
```

#### config.example.yaml

```yaml
telegram:
  token: ${TELEGRAM_TOKEN}
  allowed_users: []      # Telegram user IDs (empty = allow all)
  admin_users: []         # User IDs for /restart, /update
  allowed_chats: []       # Chat IDs for group filtering (empty = allow all)
```

#### load_config() Changes

The `load_config()` function in `config.py` (around line 211) must be updated to parse the new `TelegramConfig` fields:

```python
# In _parse_telegram_config():
admin_users = tg_data.get("admin_users", [])
allowed_chats = tg_data.get("allowed_chats", [])
return TelegramConfig(
    token=token,
    allowed_users=allowed_users,
    admin_users=admin_users,
    allowed_chats=allowed_chats,
)
```

### File Structure After Refactor

```
head/
├── __init__.py
├── main.py                    # Entry point (construct adapter + engine)
├── config.py                  # Modified: new TelegramConfig fields, load_config() updates
├── session_router.py          # Unchanged
├── ssh_manager.py             # Unchanged
├── daemon_client.py           # Unchanged
├── message_formatter.py       # Minor: no <discord_file> references (markers move to engine)
├── name_generator.py          # Unchanged
├── file_pool.py               # Refactored: remove Discord dependency, add store_file/store_from_path
│
├── platform/                  # NEW: platform adaptation layer
│   ├── __init__.py
│   ├── protocol.py            # PlatformAdapter, MessageHandle, FileAttachment
│   ├── discord_adapter.py     # DiscordAdapter (extracted from bot_discord.py)
│   ├── telegram_adapter.py    # TelegramAdapter (rewritten from bot_telegram.py)
│   └── format_utils.py        # markdown_to_telegram_html, etc.
│
├── engine.py                  # BotEngine (refactored from bot_base.py)
│
├── bot_base.py                # DELETED (logic moved to engine.py)
├── bot_discord.py             # DELETED (moved to platform/discord_adapter.py)
└── bot_telegram.py            # DELETED (moved to platform/telegram_adapter.py)
```

### main.py Initialization

```python
adapters = []
engines = []

if config.bot.discord:
    discord_adapter = DiscordAdapter(config.bot.discord)
    discord_engine = BotEngine(discord_adapter, ssh, router, daemon, config, file_pool)
    discord_adapter.set_input_handler(discord_engine.handle_input)
    adapters.append(discord_adapter)

if config.bot.telegram:
    telegram_adapter = TelegramAdapter(config.bot.telegram)
    telegram_engine = BotEngine(telegram_adapter, ssh, router, daemon, config, file_pool)
    telegram_adapter.set_input_handler(telegram_engine.handle_input)
    adapters.append(telegram_adapter)

await asyncio.gather(*(a.start() for a in adapters))
```

## Migration Strategy

Three phases, each independently mergeable:

| Phase | Content | Risk | Validation |
|-------|---------|------|------------|
| **Phase 1: Abstraction** | Introduce `platform/protocol.py`, create `engine.py`. Extract logic from `bot_base.py` into engine. Wrap existing `bot_discord.py` logic into `DiscordAdapter`. Handle deferred interactions, `_channels` cache, `_init_shown` state within the adapter. Ensure Discord works without regression. | Medium-High (large code movement; Discord has deep coupling with deferred interactions and channel caching) | All existing Discord tests pass; manual Discord smoke test **including slash commands and file upload** |
| **Phase 2: FilePool** | Generalize FilePool. Remove `download_discord_attachment`, replace with `store_file`/`store_from_path`. DiscordAdapter implements `download_file`. Rename `<discord_file>` markers to `<file_ref>`. | Low | File transfer tests pass; Discord file upload still works |
| **Phase 3: Telegram** | Implement full TelegramAdapter. File transfer, HTML formatting, typing, heartbeat, admin permissions, rate limit handling, group chat support. Delete old `bot_telegram.py`. | Low | New Telegram-specific tests; manual Telegram smoke test |

**Note on asyncio.gather for startup:** `DiscordAdapter.start()` calls `bot.start(token)` which blocks the event loop (Discord.py's design). `TelegramAdapter.start()` initializes polling and returns. Both work correctly under `asyncio.gather` since each runs as a separate coroutine, but implementers should be aware of this behavioral difference.

**Shared state safety:** Multiple `BotEngine` instances share `SessionRouter` (SQLite, per-call connections) and `SSHManager` (uses asyncio locks). These are already concurrency-safe. No additional synchronization is needed.

## Testing Strategy

- **Unit tests**: Mock `PlatformAdapter` to test `BotEngine` in isolation.
- **Adapter tests**: Test each adapter's `send_message`, `edit_message`, `download_file` with mocked platform APIs.
- **Integration tests**: Existing `test_bot_commands.py` should continue to pass by injecting a mock adapter into `BotEngine`.
- **FilePool tests**: Existing `test_file_pool.py` updated to use `store_file` instead of `download_discord_attachment`.

## Future Extensibility

Adding a new platform (e.g., Lark/Feishu) requires:

1. Create `head/platform/lark_adapter.py` implementing `PlatformAdapter`
2. Add `LarkConfig` dataclass to `config.py`
3. Add initialization block in `main.py`
4. Add platform-specific format conversion to `format_utils.py` if needed

No changes to `engine.py`, `file_pool.py`, or any other core module.
