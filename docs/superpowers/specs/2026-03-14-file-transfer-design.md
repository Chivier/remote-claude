# File Transfer Pipeline: Discord → Remote Machine (MVP)

**Date**: 2026-03-14
**Scope**: Single-direction file transfer from Discord attachments to remote Claude CLI sessions
**Approach**: SCP via existing SSH tunnels with message-level path substitution

## Problem

Users want to share files (PDFs, images, audio, video, markdown, text) from Discord with the remote Claude CLI session. Currently the entire pipeline only handles plain text messages. There is no mechanism to transfer binary files from Discord through Head to the remote daemon, nor to rewrite file references in messages so Claude CLI can access them on the remote machine.

## Requirements

1. Users can upload files in Discord (drag-and-drop or attach) alongside a message
2. Supported file types: markdown, text, PDF, images, video, audio (code files excluded for now)
3. Head maintains a local file pool with configurable max size (default 1GB)
4. Files are SCP'd to the remote machine before the message is sent to Claude
5. Message text uses `<discord_file>file_id</discord_file>` markers that get replaced with actual remote paths before reaching Claude CLI
6. User-typed paths in messages (referring to remote machine paths) are NOT modified
7. Daemon requires zero changes — it receives fully resolved text messages
8. Reverse transfer (Remote → Discord) is out of scope for this MVP

## Architecture

### Data Flow

```
Discord User
  └─ Sends message + attachment(report.pdf)
      └─ bot_discord.py: on_message()
          ├─ file_pool.download_discord_attachment(att)
          │   → Downloads to ~/.codecast/file-pool/abc123_report.pdf
          ├─ Builds message: "Analyze this <discord_file>abc123</discord_file>"
          └─ _forward_message_with_heartbeat(text, file_refs=[entry])
              │
              │ NOTE: Discord bot uses _forward_message_with_heartbeat (NOT _forward_message).
              │ The file upload + path substitution logic goes into _upload_and_replace_files(),
              │ a shared helper called by BOTH _forward_message and _forward_message_with_heartbeat.
              │
              ├─ bot_base._upload_and_replace_files(machine_id, text, file_refs)
              │   ├─ ssh_manager.upload_files(machine_id, file_refs)
              │   │   → SCP to /tmp/codecast/files/abc123_report.pdf
              │   │   → Returns {"abc123": "/tmp/codecast/files/abc123_report.pdf"}
              │   └─ Replaces: "Analyze this /tmp/codecast/files/abc123_report.pdf"
              └─ daemon_client.send_message(port, session_id, replaced_msg)
                  → Daemon receives plain text with valid remote paths
```

### Component Diagram

```
┌────────────────────────┐
│     Discord User       │
│  (uploads report.pdf)  │
└──────────┬─────────────┘
           │ message.attachments
           ▼
┌────────────────────────┐     ┌─────────────────────┐
│   bot_discord.py       │────▶│   FilePool           │
│   on_message()         │     │   ~/.codecast/  │
│                        │     │   file-pool/          │
└──────────┬─────────────┘     └─────────────────────┘
           │ text + file_refs
           ▼
┌────────────────────────┐     ┌─────────────────────┐
│   bot_discord.py       │────▶│   ssh_manager.py     │
│ _forward_message_      │     │   upload_files()     │
│ with_heartbeat() calls │     │   asyncssh.scp()     │
│ _upload_and_replace()  │     │                      │
└──────────┬─────────────┘     └──────────┬──────────┘
           │ replaced text                 │ SCP via SSH tunnel
           ▼                               ▼
┌────────────────────────┐     ┌─────────────────────┐
│   daemon_client.py     │     │   Remote Machine     │
│   send_message()       │     │   /tmp/codecast/│
│   (unchanged)          │     │   files/abc123.pdf   │
└──────────┬─────────────┘     └─────────────────────┘
           │ RPC via SSH tunnel
           ▼
┌────────────────────────┐
│   daemon (unchanged)   │
│   session-pool.ts      │
│   → claude --print     │
│     "Analyze this      │
│      /tmp/.../abc.pdf" │
└────────────────────────┘
```

## Detailed Design

### 1. FilePool (`head/file_pool.py` — new file)

Manages a local directory of downloaded Discord attachments with LRU eviction when the pool exceeds its configured max size.

```python
@dataclass
class FileEntry:
    file_id: str          # Unique ID: {session_prefix}_{uuid_short} (short, used in markers)
    original_name: str    # Original filename from Discord
    local_path: Path      # Full path in the pool directory
    size: int             # File size in bytes
    mime_type: str        # Content type from Discord
    created_at: float     # time.time() when downloaded

class FilePool:
    def __init__(self, max_size: int, pool_dir: Path):
        """
        Args:
            max_size: Maximum total bytes for the pool (default 1GB)
            pool_dir: Local directory for cached files
        """

    async def download_discord_attachment(
        self, attachment: discord.Attachment, session_prefix: str = ""
    ) -> FileEntry:
        """
        Download a Discord attachment to the local pool.
        Generates unique file_id, saves to pool_dir, evicts if over max_size.
        """

    def is_allowed_type(self, filename: str, content_type: str | None) -> bool:
        """
        Check if the file type is in the allowed list.
        Matches against configured MIME patterns (e.g., "image/*").
        """

    def get_file(self, file_id: str) -> FileEntry | None:
        """Retrieve a file entry by ID."""

    def _evict_if_needed(self) -> None:
        """Remove oldest files until total_size <= max_size."""

    @property
    def total_size(self) -> int:
        """Sum of all cached file sizes."""
```

**File ID vs local filename** (important distinction):
- `file_id` = `{session_prefix}_{uuid8}` — short identifier used in `<discord_file>` markers. Example: `a1b2c3d4_f7e8d9c0`
- Local pool filename = `{file_id}_{sanitized_original_name}` — used for on-disk storage and remote filenames. Example: `a1b2c3d4_f7e8d9c0_quarterly-report.pdf`

**Filename sanitization** (`_sanitize_filename()`): Strip path separators (`/`, `\`), null bytes, leading dots, and shell metacharacters (`;`, `&`, `|`, `$`, `` ` ``, `(`, `)`, `{`, `}`). Replace spaces with hyphens. Limit to 200 characters (preserving the extension). If the result is empty after sanitization, use `"unnamed"` with the original extension.

**Eviction policy**: When `total_size > max_size`, delete files by oldest `created_at` until under limit. This is a simple LRU that runs on each new download.

**Allowed type matching**: Uses fnmatch-style patterns against MIME types. `"image/*"` matches `"image/png"`, `"image/jpeg"`, etc. Filenames are also checked by extension as a fallback when Discord doesn't provide content_type.

### 2. Discord Attachment Handling (`head/bot_discord.py`)

Modify `on_message` to detect and process attachments:

```python
@self.bot.event
async def on_message(message: discord.Message) -> None:
    # ... existing checks (bot messages, slash commands, allowed channels) ...

    channel_id = f"discord:{message.channel.id}"
    self._channels[channel_id] = message.channel

    # Process attachments
    file_refs: list[FileEntry] = []
    if message.attachments:
        session = self.router.resolve(channel_id)
        session_prefix = session.daemon_session_id[:8] if session else "nosess"

        for att in message.attachments:
            if not self.file_pool.is_allowed_type(att.filename, att.content_type):
                await message.channel.send(
                    f"Skipping unsupported file: `{att.filename}` ({att.content_type})"
                )
                continue
            try:
                entry = await self.file_pool.download_discord_attachment(
                    att, session_prefix=session_prefix
                )
                file_refs.append(entry)
            except Exception as e:
                await message.channel.send(f"Failed to download `{att.filename}`: {e}")

    # Build message with file markers
    text = message.content or ""
    if file_refs:
        for ref in file_refs:
            text += f"\n<discord_file>{ref.file_id}</discord_file>"

    # Handle case: only attachments, no text
    if not text.strip() and not file_refs:
        return

    await self._forward_message_with_heartbeat(channel_id, text, file_refs=file_refs)
```

### 3. Message Forwarding with File Upload (`head/bot_base.py` + `head/bot_discord.py`)

**Key architecture note**: Discord uses `_forward_message_with_heartbeat` in `bot_discord.py` (which is a complete, self-contained reimplementation of the streaming loop with typing indicator and heartbeat — it does NOT delegate to `_forward_message`). Telegram and the base class use `_forward_message`. Both code paths need the file upload logic.

To avoid duplication, we add a shared helper method `_upload_and_replace_files()` to `BotBase`:

```python
# In bot_base.py — new shared helper:

async def _upload_and_replace_files(
    self,
    machine_id: str,
    text: str,
    file_refs: list | None = None,
) -> str:
    """
    Upload file_refs to the remote machine via SCP and replace
    <discord_file>file_id</discord_file> markers with actual remote paths.

    Returns the text with all markers replaced.
    Raises on upload failure (caller should handle).
    """
    if not file_refs:
        return text

    path_mapping = await self.ssh.upload_files(machine_id, file_refs)
    for file_id, remote_path in path_mapping.items():
        text = text.replace(
            f"<discord_file>{file_id}</discord_file>",
            remote_path
        )
    return text
```

Then modify `_forward_message` in `bot_base.py`:

```python
async def _forward_message(
    self, channel_id: str, text: str, file_refs: list | None = None
) -> None:
    session = self.router.resolve(channel_id)
    if not session:
        await self.send_message(channel_id, "No active session...")
        return

    if channel_id in self._streaming:
        await self.send_message(channel_id, "Claude is still processing...")
        return

    self._streaming.add(channel_id)

    try:
        local_port = await self.ssh.ensure_tunnel(session.machine_id)

        # Upload files and replace markers
        if file_refs:
            try:
                text = await self._upload_and_replace_files(
                    session.machine_id, text, file_refs
                )
            except Exception as e:
                await self.send_message(
                    channel_id, format_error(f"File upload failed: {e}")
                )
                return

        # ... rest of streaming logic (unchanged) ...
```

And modify `_forward_message_with_heartbeat` in `bot_discord.py`:

```python
async def _forward_message_with_heartbeat(
    self, channel_id: str, text: str, file_refs: list | None = None
) -> None:
    """Forward a user message to Claude with typing indicator, heartbeat, and file upload."""
    session = self.router.resolve(channel_id)
    if not session:
        await self.send_message(channel_id, "No active session...")
        return

    if channel_id in self._streaming:
        await self.send_message(channel_id, "Claude is still processing...")
        return

    self._streaming.add(channel_id)

    # ... existing event_tracker, typing, heartbeat setup ...

    try:
        local_port = await self.ssh.ensure_tunnel(session.machine_id)

        # Upload files and replace markers (BEFORE streaming starts)
        if file_refs:
            try:
                text = await self._upload_and_replace_files(
                    session.machine_id, text, file_refs
                )
            except Exception as e:
                await self.send_message(
                    channel_id, format_error(f"File upload failed: {e}")
                )
                return

        # ... rest of existing streaming loop (unchanged) ...
```

### 4. SSH File Upload (`head/ssh_manager.py`)

Add `upload_files` method to SSHManager:

```python
async def upload_files(
    self,
    machine_id: str,
    file_entries: list,  # list[FileEntry]
    remote_base: str | None = None,
) -> dict[str, str]:
    """
    SCP files to the remote machine.

    Args:
        machine_id: Target machine
        file_entries: List of FileEntry objects to upload
        remote_base: Remote directory (default from config)

    Returns:
        Dict mapping file_id -> remote_path
    """
    if not remote_base:
        remote_base = self.config.file_pool.remote_dir

    # Get SSH connection (reuse tunnel connection)
    if machine_id not in self.tunnels or not self.tunnels[machine_id].alive:
        raise ValueError(f"No active tunnel to {machine_id}")
    conn = self.tunnels[machine_id].conn

    # Ensure remote directory exists
    await conn.run(f"mkdir -p {remote_base}")

    mapping: dict[str, str] = {}
    for entry in file_entries:
        remote_filename = f"{entry.file_id}_{entry.original_name}"
        remote_path = f"{remote_base}/{remote_filename}"
        await asyncssh.scp(str(entry.local_path), (conn, remote_path))
        mapping[entry.file_id] = remote_path
        logger.info(
            f"Uploaded {entry.original_name} to {machine_id}:{remote_path}"
        )

    return mapping
```

### 5. Configuration (`head/config.py`, `config.example.yaml`)

New `FilePoolConfig` dataclass:

```python
@dataclass
class FilePoolConfig:
    max_size: int = 1073741824          # 1GB in bytes
    pool_dir: str = "~/.codecast/file-pool"
    remote_dir: str = "/tmp/codecast/files"
    allowed_types: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_TYPES))
```

Wire into the `Config` dataclass:

```python
# In Config dataclass (config.py):
@dataclass
class Config:
    machines: dict[str, MachineConfig]
    bot: BotConfig
    default_mode: str = "auto"
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    daemon: DaemonDeployConfig = field(default_factory=DaemonDeployConfig)
    file_pool: FilePoolConfig = field(default_factory=FilePoolConfig)  # NEW
```

Add parsing in `load_config()`:

```python
# Default allowed types constant (shared between dataclass and loader)
DEFAULT_ALLOWED_TYPES = [
    "text/plain",
    "text/markdown",
    "application/pdf",
    "image/*",
    "video/*",
    "audio/*",
]

# In load_config() — after existing parsing:
file_pool_raw = raw.get("file_pool", {})
config.file_pool = FilePoolConfig(
    max_size=file_pool_raw.get("max_size", 1073741824),
    pool_dir=expand_env_vars(file_pool_raw.get("pool_dir", "~/.codecast/file-pool")),
    remote_dir=file_pool_raw.get("remote_dir", "/tmp/codecast/files"),
    allowed_types=file_pool_raw.get("allowed_types", DEFAULT_ALLOWED_TYPES),
)
```

New section in `config.example.yaml`:

```yaml
# File transfer settings
file_pool:
  max_size: 1073741824              # Max pool size in bytes (default: 1GB)
  pool_dir: ~/.codecast/file-pool  # Local file cache directory
  remote_dir: /tmp/codecast/files  # Remote file staging directory
  allowed_types:                    # MIME type patterns for allowed files
    - text/plain
    - text/markdown
    - application/pdf
    - "image/*"
    - "video/*"
    - "audio/*"
```

The `max_size` field accepts an integer (bytes) only. Human-readable formats like `"1GB"` are out of scope for MVP.

### 6. Initialization (`head/main.py`, constructor changes)

**`DiscordBot.__init__` signature change** (Discord-only, since Telegram file handling is out of scope):

```python
# In bot_discord.py:
class DiscordBot(BotBase):
    def __init__(
        self,
        ssh_manager: SSHManager,
        session_router: SessionRouter,
        daemon_client: DaemonClient,
        config: Config,
        file_pool: FilePool | None = None,  # NEW — optional for backwards compat
    ):
        super().__init__(ssh_manager, session_router, daemon_client, config)
        self.file_pool = file_pool
        # ... rest of __init__ unchanged ...
```

Wire FilePool into the application startup:

```python
# In main():
file_pool = FilePool(
    max_size=config.file_pool.max_size,
    pool_dir=Path(config.file_pool.pool_dir).expanduser(),
)

# Pass to Discord bot
discord_bot = DiscordBot(
    ssh_manager=ssh_manager,
    session_router=session_router,
    daemon_client=daemon_client,
    config=config,
    file_pool=file_pool,  # new parameter
)
```

## Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `head/file_pool.py` | New | File pool manager with LRU eviction |
| `head/config.py` | Modified | Add `FilePoolConfig` dataclass, wire into `Config` and `load_config()` |
| `config.example.yaml` | Modified | Add `file_pool` configuration section |
| `head/bot_discord.py` | Modified | Handle `message.attachments` in `on_message()`, add `file_pool` to `__init__`, extend `_forward_message_with_heartbeat` to accept `file_refs` |
| `head/bot_base.py` | Modified | Add `_upload_and_replace_files()` helper, extend `_forward_message()` with `file_refs` param |
| `head/ssh_manager.py` | Modified | Add `upload_files()` method |
| `head/main.py` | Modified | Initialize `FilePool`, pass to `DiscordBot` constructor |
| `daemon/` | **No changes** | Daemon receives already-resolved text messages |

## Testing Strategy

### Unit Tests

1. **`tests/test_file_pool.py`** (new):
   - Download simulation (mock Discord attachment)
   - File ID generation uniqueness
   - Allowed type checking (exact match, wildcard match, rejection)
   - LRU eviction when over max_size
   - `get_file` retrieval
   - `total_size` calculation

2. **`tests/test_bot_commands.py`** (extend):
   - Message with attachments → file markers appended
   - Message with unsupported attachment type → skipped with notification
   - Message with mixed supported/unsupported attachments
   - Attachment-only message (no text) → markers still sent
   - No session active → attachments ignored with error

3. **`tests/test_ssh_manager.py`** (new or extend):
   - `upload_files` creates remote directory
   - `upload_files` SCPs each file and returns correct mapping
   - `upload_files` with no active tunnel → error

4. **`tests/test_bot_commands.py`** (extend existing — reuse `MockBot` pattern):
   - Path substitution: `<discord_file>id</discord_file>` → remote path
   - Multiple file refs in one message
   - Upload failure → error message sent, message not forwarded
   - File refs with no matching markers (edge case)

### Integration Test (manual)

1. Start a session: `/start gpu-1 /home/user/project`
2. Upload a PDF in Discord: "Analyze this report" + attach report.pdf
3. Verify: file appears in remote `/tmp/codecast/files/`
4. Verify: Claude receives message with correct remote path
5. Test with image, audio, video files
6. Test with unsupported file (e.g., `.py`) → should be skipped

## Edge Cases

- **No active session**: If user uploads a file without `/start`, the attachment is still in the Discord message but `session_prefix` defaults to `"nosess"`. The forward will fail gracefully with "No active session" error.
- **File too large for pool**: If a single file exceeds `max_size`, the download should fail with a clear error message.
- **SCP failure**: If SSH connection drops during SCP, the error bubbles up to `_forward_message` which sends an error message to the Discord channel. The message is NOT forwarded to Claude.
- **Multiple files in one message**: All files are uploaded, all markers are replaced. If any upload fails, the entire message is aborted.
- **Concurrent uploads**: The `_streaming` lock in `bot_base.py` prevents concurrent message forwarding for the same channel, so file uploads for the same channel are serialized.
- **Orphaned pool files**: If a file is downloaded to the pool but SCP fails (e.g., tunnel dies), the file remains in the local pool but is never sent. This is benign — LRU eviction will eventually clean it up. No special handling needed for MVP.

## Out of Scope (Future Work)

- Reverse file transfer: Remote → Discord (Claude-generated files sent back to user)
- File deduplication (same file uploaded multiple times)
- Telegram bot file handling
- Large file streaming (files > Discord's upload limit are already handled by Discord itself)
- Code file transfer (`.py`, `.js`, `.ts`, etc.)
- File content extraction (e.g., OCR for images, text extraction from PDFs)
