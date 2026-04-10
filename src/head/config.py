"""
Configuration loader for Codecast Head Node.
Reads config.yaml and expands environment variables.
"""

import logging
import os
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ruamel.yaml import YAML

logger = logging.getLogger(__name__)


@dataclass
class PeerConfig:
    """A remote (or local) peer that runs the daemon.

    This is the unified config type for all machines/peers. For backward
    compatibility, properties ``host``, ``user``, ``port``, and ``localhost``
    are provided as aliases for the SSH / transport fields.
    """

    id: str
    transport: str = "ssh"  # "http", "ssh", or "local"
    address: Optional[str] = None  # For HTTP transport: full URL
    token: Optional[str] = None  # For HTTP transport: auth token
    tls_fingerprint: Optional[str] = None  # For HTTP transport: pin TLS cert
    ssh_host: Optional[str] = None  # For SSH transport: hostname or IP
    ssh_user: Optional[str] = None  # For SSH transport: username
    ssh_key: Optional[str] = None  # For SSH transport: path to key file
    ssh_port: int = 22  # For SSH transport: port
    proxy_jump: Optional[str] = None  # For SSH transport: ProxyJump host
    proxy_command: Optional[str] = None  # For SSH transport: ProxyCommand
    password: Optional[str] = None  # For SSH transport: password or file: path
    daemon_port: int = 9100  # Port daemon listens on
    node_path: Optional[str] = None  # Path to node binary on peer
    project_path: str = "~/Projects"  # Base dir for short-name path expansion
    default_paths: list[str] = field(default_factory=list)

    # ── Backward-compat properties (MachineConfig interface) ──

    @property
    def host(self) -> str:
        return self.ssh_host or ""

    @property
    def user(self) -> str:
        return self.ssh_user or ""

    @property
    def port(self) -> int:
        return self.ssh_port

    @property
    def localhost(self) -> bool:
        return self.transport == "local"


# Backward-compat alias so ``from head.config import MachineConfig`` still works.
MachineConfig = PeerConfig


@dataclass
class DiscordConfig:
    token: str
    allowed_channels: list[int] = field(default_factory=list)
    command_prefix: str = "/"
    admin_users: list[int] = field(default_factory=list)  # Discord user IDs for /restart, /update


@dataclass
class TelegramConfig:
    token: str
    allowed_users: list[int] = field(default_factory=list)
    admin_users: list[int] = field(default_factory=list)
    allowed_chats: list[int] = field(default_factory=list)


@dataclass
class LarkConfig:
    app_id: str
    app_secret: str
    allowed_chats: list[str] = field(default_factory=list)
    admin_users: list[str] = field(default_factory=list)
    use_cards: bool = True


@dataclass
class WebUIConfig:
    enabled: bool = False
    port: int = 8080
    host: str = "127.0.0.1"


@dataclass
class FileForwardRule:
    pattern: str
    max_size: int = 5 * 1024 * 1024
    auto: bool = False


@dataclass
class FileForwardConfig:
    enabled: bool = False
    rules: list[FileForwardRule] = field(default_factory=list)
    default_max_size: int = 5 * 1024 * 1024
    default_auto: bool = False
    download_dir: str = "~/.codecast/downloads"


@dataclass
class BotConfig:
    discord: Optional[DiscordConfig] = None
    telegram: Optional[TelegramConfig] = None
    lark: Optional[LarkConfig] = None
    webui: Optional[WebUIConfig] = None


@dataclass
class SkillsConfig:
    shared_dir: str = "./skills"
    sync_on_start: bool = True


@dataclass
class DaemonDeployConfig:
    install_dir: str = "~/.codecast/daemon"
    auto_deploy: bool = True
    log_file: str = "~/.codecast/daemon.log"


DEFAULT_ALLOWED_FILE_TYPES = [
    "text/plain",
    "text/markdown",
    "application/pdf",
    "image/*",
    "video/*",
    "audio/*",
]


@dataclass
class FilePoolConfig:
    max_size: int = 1073741824  # 1GB in bytes
    pool_dir: str = "~/.codecast/file-pool"
    remote_dir: str = "/tmp/codecast/files"
    allowed_types: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_FILE_TYPES))


@dataclass
class Config:
    peers: dict[str, PeerConfig] = field(default_factory=dict)
    bot: BotConfig = field(default_factory=BotConfig)
    default_mode: str = "auto"
    tool_batch_size: int = 15  # Number of tool_use messages to batch into one
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    daemon: DaemonDeployConfig = field(default_factory=DaemonDeployConfig)
    file_pool: FilePoolConfig = field(default_factory=FilePoolConfig)
    file_forward: FileForwardConfig = field(default_factory=FileForwardConfig)
    config_path: str | None = field(default=None, repr=False)

    @property
    def machines(self) -> dict[str, PeerConfig]:
        """Backward-compat alias: ``config.machines`` -> ``config.peers``."""
        return self.peers


# Backward-compat aliases
DaemonConfig = DaemonDeployConfig
DiscordBotConfig = DiscordConfig
TelegramBotConfig = TelegramConfig


def expand_env_vars(value: str) -> str:
    """Expand ${ENV_VAR} references in a string."""

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))

    return re.sub(r"\$\{(\w+)\}", replacer, value)


def _is_localhost(host: str) -> bool:
    """Check if a host string refers to the local machine.

    Checks against: localhost, 127.0.0.1, ::1, current hostname,
    and all local network interface IPs.
    """
    host_lower = host.lower()
    if host_lower in ("localhost", "127.0.0.1", "::1"):
        return True

    import socket

    # Check hostname
    try:
        if host_lower == socket.gethostname().lower():
            return True
        if host_lower == socket.getfqdn().lower():
            return True
    except Exception:
        pass

    # Check all local IPs
    try:
        local_ips = set()
        for info in socket.getaddrinfo(socket.gethostname(), None):
            local_ips.add(info[4][0])
        # Also grab IPs from all interfaces via subprocess (more reliable)
        import subprocess

        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for ip in result.stdout.strip().split():
                local_ips.add(ip.strip())
        if host in local_ips:
            return True
    except Exception:
        pass

    return False


def expand_path(path: str) -> str:
    """Expand ~ and environment variables in a path."""
    return str(Path(expand_env_vars(path)).expanduser())


def _process_value(value: Any) -> Any:
    """Recursively expand env vars in config values."""
    if isinstance(value, str):
        return expand_env_vars(value)
    elif isinstance(value, dict):
        return {k: _process_value(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_process_value(item) for item in value]
    return value


def load_config(config_path: str = "config.yaml") -> Config:
    """Load and parse a config file.

    Expects the ``peers:`` YAML key for machine definitions.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path) as f:
        raw_data: dict[str, Any] = yaml.safe_load(f)

    if not raw_data:
        raise ValueError("Config file is empty")

    # Expand env vars throughout
    raw: dict[str, Any] = _process_value(raw_data)

    cfg = Config()

    # Parse peers
    peers_raw: dict[str, Any] = raw.get("peers", {})
    if peers_raw:
        for peer_id, peer_data in peers_raw.items():
            cfg.peers[peer_id] = _parse_peer(peer_id, peer_data or {})

    # Parse bot
    bot_raw: dict[str, Any] = raw.get("bot", {})
    if bot_raw:
        cfg.bot = _parse_bot(bot_raw)

    # Scalar settings
    cfg.default_mode = raw.get("default_mode", "auto")
    cfg.tool_batch_size = _safe_int(raw.get("tool_batch_size", 15), 15)

    # Skills
    skills_raw: dict[str, Any] = raw.get("skills", {})
    if skills_raw:
        cfg.skills = SkillsConfig(
            shared_dir=skills_raw.get("shared_dir", "./skills"),
            sync_on_start=skills_raw.get("sync_on_start", True),
        )

    # Daemon
    daemon_raw: dict[str, Any] = raw.get("daemon", {})
    if daemon_raw:
        cfg.daemon = DaemonDeployConfig(
            install_dir=daemon_raw.get("install_dir", "~/.codecast/daemon"),
            auto_deploy=daemon_raw.get("auto_deploy", True),
            log_file=daemon_raw.get("log_file", "~/.codecast/daemon.log"),
        )

    # File pool
    file_pool_raw: dict[str, Any] = raw.get("file_pool", {})
    if file_pool_raw:
        cfg.file_pool = FilePoolConfig(
            max_size=file_pool_raw.get("max_size", 1073741824),
            pool_dir=expand_env_vars(file_pool_raw.get("pool_dir", "~/.codecast/file-pool")),
            remote_dir=file_pool_raw.get("remote_dir", "/tmp/codecast/files"),
            allowed_types=file_pool_raw.get("allowed_types", list(DEFAULT_ALLOWED_FILE_TYPES)),
        )

    # File forward
    file_forward_raw: dict[str, Any] = raw.get("file_forward", {})
    if file_forward_raw:
        rules = []
        for rule_raw in file_forward_raw.get("rules", []):
            rules.append(
                FileForwardRule(
                    pattern=rule_raw.get("pattern", "*"),
                    max_size=rule_raw.get("max_size", 5 * 1024 * 1024),
                    auto=rule_raw.get("auto", False),
                )
            )
        cfg.file_forward = FileForwardConfig(
            enabled=file_forward_raw.get("enabled", False),
            rules=rules,
            default_max_size=file_forward_raw.get("default_max_size", 5 * 1024 * 1024),
            default_auto=file_forward_raw.get("default_auto", False),
            download_dir=file_forward_raw.get("download_dir", "~/.codecast/downloads"),
        )

    cfg.config_path = str(path.resolve())

    return cfg


# ─── Config Persistence (add/remove machines) ───


def _get_config_path(config: Config) -> Path:
    """Get the config file path. Falls back to 'config.yaml' in project root."""
    if config.config_path is not None:
        return Path(config.config_path)
    # __file__ is src/head/config.py, so .parent.parent.parent is the project root
    return Path(__file__).parent.parent.parent / "config.yaml"


def save_machine_to_config(config: Config, machine: PeerConfig) -> None:
    """
    Add or update a machine/peer entry in config.yaml using ruamel.yaml
    to preserve comments and formatting.
    """
    config_path = _get_config_path(config)
    ryaml = YAML()
    ryaml.preserve_quotes = True  # type: ignore[assignment]

    with open(config_path) as f:
        doc = ryaml.load(f)

    if "peers" not in doc or doc["peers"] is None:
        doc["peers"] = {}

    # Build peer dict
    m: dict[str, Any] = {"transport": machine.transport}
    if machine.ssh_host:
        m["ssh_host"] = machine.ssh_host
    if machine.ssh_user:
        m["ssh_user"] = machine.ssh_user
    if machine.ssh_key:
        m["ssh_key"] = machine.ssh_key
    if machine.ssh_port != 22:
        m["ssh_port"] = machine.ssh_port
    if machine.address:
        m["address"] = machine.address
    if machine.token:
        m["token"] = machine.token
    if machine.tls_fingerprint:
        m["tls_fingerprint"] = machine.tls_fingerprint
    if machine.proxy_jump:
        m["proxy_jump"] = machine.proxy_jump
    if machine.proxy_command:
        m["proxy_command"] = machine.proxy_command
    if machine.password:
        m["password"] = machine.password
    m["daemon_port"] = machine.daemon_port
    if machine.node_path:
        m["node_path"] = machine.node_path
    if machine.project_path != "~/Projects":
        m["project_path"] = machine.project_path
    if machine.default_paths:
        m["default_paths"] = machine.default_paths

    doc["peers"][machine.id] = m

    with open(config_path, "w") as f:
        ryaml.dump(doc, f)

    logger.info(f"Saved machine '{machine.id}' to {config_path}")


def remove_machine_from_config(config: Config, machine_id: str) -> None:
    """
    Remove a machine entry from config.yaml using ruamel.yaml
    to preserve comments and formatting.
    """
    config_path = _get_config_path(config)
    ryaml = YAML()
    ryaml.preserve_quotes = True  # type: ignore[assignment]

    with open(config_path) as f:
        doc = ryaml.load(f)

    removed = False
    if "peers" in doc and doc["peers"] and machine_id in doc["peers"]:
        del doc["peers"][machine_id]
        removed = True
    if removed:
        with open(config_path, "w") as f:
            ryaml.dump(doc, f)
        logger.info(f"Removed machine '{machine_id}' from {config_path}")
    else:
        logger.warning(f"Machine '{machine_id}' not found in {config_path}")


# ─── SSH Config Parser ───


@dataclass
class SSHHostEntry:
    """Parsed entry from ~/.ssh/config."""

    name: str
    hostname: Optional[str] = None
    user: Optional[str] = None
    port: int = 22
    proxy_jump: Optional[str] = None
    proxy_command: Optional[str] = None
    identity_file: Optional[str] = None


def parse_ssh_config(config_path: Optional[str] = None) -> list[SSHHostEntry]:
    """
    Parse ~/.ssh/config (including Include directives) and return
    a list of SSHHostEntry objects.

    Skips wildcard hosts (e.g., Host *) and github.com.
    """
    if config_path is None:
        config_path = str(Path.home() / ".ssh" / "config")

    path = Path(config_path)
    if not path.exists():
        return []

    return _parse_ssh_config_file(path, set())


def _parse_ssh_config_file(path: Path, visited: set[str]) -> list[SSHHostEntry]:
    """Recursively parse an SSH config file, handling Include directives."""
    resolved = path.resolve()
    if str(resolved) in visited:
        return []
    visited.add(str(resolved))

    entries: list[SSHHostEntry] = []
    current: Optional[SSHHostEntry] = None

    try:
        lines = path.read_text().splitlines()
    except (OSError, PermissionError):
        return []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Parse key-value
        parts = stripped.split(None, 1)
        if len(parts) < 2:
            continue

        key = parts[0].lower()
        value = parts[1].strip().strip('"')

        if key == "include":
            # Resolve include path relative to the SSH config directory
            include_pattern = value
            if include_pattern.startswith("~"):
                include_pattern = str(Path.home()) + include_pattern[1:]
            elif not include_pattern.startswith("/"):
                include_pattern = str(path.parent / include_pattern)

            # Handle glob patterns
            from glob import glob as globfn

            for inc_path in sorted(globfn(include_pattern)):
                entries.extend(_parse_ssh_config_file(Path(inc_path), visited))
            continue

        if key == "host":
            # New host block
            host_name = value
            # Skip wildcard and github entries
            if "*" in host_name or host_name.lower() == "github.com":
                current = None
                continue
            current = SSHHostEntry(name=host_name)
            entries.append(current)
            continue

        if current is None:
            continue

        if key == "hostname":
            current.hostname = value
        elif key == "user":
            current.user = value
        elif key == "port":
            try:
                current.port = int(value)
            except ValueError:
                pass
        elif key == "proxyjump":
            current.proxy_jump = value
        elif key == "proxycommand":
            current.proxy_command = value
        elif key == "identityfile":
            current.identity_file = value

    return entries


def format_ssh_hosts_for_display(entries: list[SSHHostEntry]) -> str:
    """Format SSH host entries for display in chat, with index numbers."""
    if not entries:
        return "No SSH hosts found in `~/.ssh/config`."

    lines = [f"**SSH Hosts** ({len(entries)} found):"]
    lines.append("```")
    for i, e in enumerate(entries, 1):
        host_str = e.hostname or "(no hostname)"
        user_str = f"  user={e.user}" if e.user else ""
        proxy_str = f"  proxy={e.proxy_jump}" if e.proxy_jump else ""
        port_str = f"  port={e.port}" if e.port != 22 else ""
        lines.append(f"{i:3d}. {e.name:<25s} {host_str}{user_str}{proxy_str}{port_str}")
    lines.append("```")
    lines.append("\nReply with the **numbers** of hosts to add (e.g., `1 3 5`).")
    return "\n".join(lines)


# ─── Config Helpers ───


def _parse_peer(peer_id: str, data: dict[str, Any]) -> PeerConfig:
    """Parse a single peer entry from config dict."""
    return PeerConfig(
        id=peer_id,
        transport=data.get("transport", "ssh"),
        address=data.get("address"),
        token=data.get("token"),
        tls_fingerprint=data.get("tls_fingerprint"),
        ssh_host=data.get("ssh_host"),
        ssh_user=data.get("ssh_user"),
        ssh_key=expand_path(data["ssh_key"]) if "ssh_key" in data else None,
        ssh_port=_safe_int(data.get("ssh_port", 22), 22),
        proxy_jump=data.get("proxy_jump"),
        proxy_command=data.get("proxy_command"),
        password=data.get("password"),
        daemon_port=_safe_int(data.get("daemon_port", 9100), 9100),
        node_path=data.get("node_path"),
        project_path=data.get("project_path", "~/Projects"),
        default_paths=data.get("default_paths", []),
    )


def _safe_int_list(values: list) -> list[int]:
    """Convert a list of values to integers, skipping invalid entries."""
    result = []
    for v in values:
        try:
            result.append(int(v))
        except (ValueError, TypeError):
            logger.warning(f"Ignoring non-integer value in config list: {v!r}")
    return result


def _safe_int(value: Any, default: int) -> int:
    """Convert a value to int with fallback to default."""
    try:
        return int(value)
    except (ValueError, TypeError):
        logger.warning(f"Invalid integer value {value!r}, using default {default}")
        return default


def _parse_bot(raw: dict[str, Any]) -> BotConfig:
    """Parse bot section from config (all platforms)."""
    bot = BotConfig()

    discord_raw = raw.get("discord")
    if discord_raw:
        bot.discord = DiscordConfig(
            token=discord_raw.get("token", ""),
            allowed_channels=_safe_int_list(discord_raw.get("allowed_channels", [])),
            command_prefix=discord_raw.get("command_prefix", "/"),
            admin_users=_safe_int_list(discord_raw.get("admin_users", [])),
        )

    telegram_raw = raw.get("telegram")
    if telegram_raw:
        bot.telegram = TelegramConfig(
            token=telegram_raw.get("token", ""),
            allowed_users=_safe_int_list(telegram_raw.get("allowed_users", [])),
            admin_users=_safe_int_list(telegram_raw.get("admin_users", [])),
            allowed_chats=_safe_int_list(telegram_raw.get("allowed_chats", [])),
        )

    lark_raw = raw.get("lark")
    if lark_raw:
        bot.lark = LarkConfig(
            app_id=lark_raw.get("app_id", ""),
            app_secret=lark_raw.get("app_secret", ""),
            allowed_chats=[str(c) for c in lark_raw.get("allowed_chats", [])],
            admin_users=[str(u) for u in lark_raw.get("admin_users", [])],
            use_cards=lark_raw.get("use_cards", True),
        )

    webui_raw = raw.get("webui")
    if webui_raw:
        bot.webui = WebUIConfig(
            enabled=webui_raw.get("enabled", False),
            port=webui_raw.get("port", 8080),
            host=webui_raw.get("host", "127.0.0.1"),
        )

    return bot


# ─── Config Save ───


def save_config(cfg: Config, config_path: str) -> None:
    """Save a Config to a YAML file."""
    data: dict[str, Any] = {}

    # Peers
    if cfg.peers:
        peers_dict: dict[str, Any] = {}
        for pid, peer in cfg.peers.items():
            pd: dict[str, Any] = {"transport": peer.transport}
            if peer.address:
                pd["address"] = peer.address
            if peer.token:
                pd["token"] = peer.token
            if peer.tls_fingerprint:
                pd["tls_fingerprint"] = peer.tls_fingerprint
            if peer.ssh_host:
                pd["ssh_host"] = peer.ssh_host
            if peer.ssh_user:
                pd["ssh_user"] = peer.ssh_user
            if peer.ssh_key:
                pd["ssh_key"] = peer.ssh_key
            if peer.ssh_port != 22:
                pd["ssh_port"] = peer.ssh_port
            if peer.proxy_jump:
                pd["proxy_jump"] = peer.proxy_jump
            if peer.proxy_command:
                pd["proxy_command"] = peer.proxy_command
            if peer.password:
                pd["password"] = peer.password
            if peer.daemon_port != 9100:
                pd["daemon_port"] = peer.daemon_port
            if peer.node_path:
                pd["node_path"] = peer.node_path
            if peer.project_path != "~/Projects":
                pd["project_path"] = peer.project_path
            if peer.default_paths:
                pd["default_paths"] = peer.default_paths
            peers_dict[pid] = pd
        data["peers"] = peers_dict

    # Bot
    bot_dict: dict[str, Any] = {}
    if cfg.bot.discord:
        d = cfg.bot.discord
        dd: dict[str, Any] = {"token": d.token}
        if d.allowed_channels:
            dd["allowed_channels"] = d.allowed_channels
        if d.command_prefix != "/":
            dd["command_prefix"] = d.command_prefix
        if d.admin_users:
            dd["admin_users"] = d.admin_users
        bot_dict["discord"] = dd
    if cfg.bot.telegram:
        t = cfg.bot.telegram
        td: dict[str, Any] = {"token": t.token}
        if t.allowed_users:
            td["allowed_users"] = t.allowed_users
        if t.admin_users:
            td["admin_users"] = t.admin_users
        if t.allowed_chats:
            td["allowed_chats"] = t.allowed_chats
        bot_dict["telegram"] = td
    if getattr(cfg.bot, "lark", None):
        lk = cfg.bot.lark
        ld: dict[str, Any] = {
            "app_id": lk.app_id,
            "app_secret": lk.app_secret,
        }
        if lk.allowed_chats:
            ld["allowed_chats"] = lk.allowed_chats
        if lk.admin_users:
            ld["admin_users"] = lk.admin_users
        if not lk.use_cards:
            ld["use_cards"] = lk.use_cards
        bot_dict["lark"] = ld
    if cfg.bot.webui:
        w = cfg.bot.webui
        bot_dict["webui"] = {
            "enabled": w.enabled,
            "port": w.port,
            "host": w.host,
        }
    if bot_dict:
        data["bot"] = bot_dict

    # Scalars
    data["default_mode"] = cfg.default_mode
    data["tool_batch_size"] = cfg.tool_batch_size

    # Skills
    data["skills"] = {
        "shared_dir": cfg.skills.shared_dir,
        "sync_on_start": cfg.skills.sync_on_start,
    }

    # Daemon
    data["daemon"] = {
        "install_dir": cfg.daemon.install_dir,
        "auto_deploy": cfg.daemon.auto_deploy,
        "log_file": cfg.daemon.log_file,
    }

    # File pool
    fp = cfg.file_pool
    fp_dict: dict[str, Any] = {
        "max_size": fp.max_size,
        "pool_dir": fp.pool_dir,
        "remote_dir": fp.remote_dir,
    }
    if fp.allowed_types != list(DEFAULT_ALLOWED_FILE_TYPES):
        fp_dict["allowed_types"] = fp.allowed_types
    data["file_pool"] = fp_dict

    # File forward
    ff = cfg.file_forward
    ff_dict: dict[str, Any] = {
        "enabled": ff.enabled,
        "default_max_size": ff.default_max_size,
        "default_auto": ff.default_auto,
        "download_dir": ff.download_dir,
    }
    if ff.rules:
        ff_dict["rules"] = [{"pattern": r.pattern, "max_size": r.max_size, "auto": r.auto} for r in ff.rules]
    data["file_forward"] = ff_dict

    path = Path(config_path)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Saved config to {config_path}")
