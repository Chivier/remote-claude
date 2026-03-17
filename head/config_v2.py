"""
Config V2 parser for Codecast.

New format uses 'peers' (not 'machines') with explicit transport modes
(http, ssh, local). Supports migration from v1 config format.
"""

import logging
import os
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─── Environment variable expansion ───


def expand_env_vars(value: str) -> str:
    """Expand ${ENV_VAR} references in a string."""

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))

    return re.sub(r"\$\{(\w+)\}", replacer, value)


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


# ─── Dataclasses ───


@dataclass
class PeerConfig:
    """A remote (or local) peer that runs the daemon."""

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
    default_paths: list[str] = field(default_factory=list)


@dataclass
class DaemonConfig:
    install_dir: str = "~/.codecast/daemon"
    auto_deploy: bool = True
    log_file: str = "~/.codecast/daemon.log"


@dataclass
class DiscordBotConfig:
    token: str = ""
    allowed_channels: list[int] = field(default_factory=list)
    command_prefix: str = "/"
    admin_users: list[int] = field(default_factory=list)


@dataclass
class TelegramBotConfig:
    token: str = ""
    allowed_users: list[int] = field(default_factory=list)
    admin_users: list[int] = field(default_factory=list)
    allowed_chats: list[int] = field(default_factory=list)


@dataclass
class WebUIConfig:
    enabled: bool = False
    port: int = 8080
    host: str = "127.0.0.1"


@dataclass
class BotConfig:
    discord: Optional[DiscordBotConfig] = None
    telegram: Optional[TelegramBotConfig] = None
    webui: Optional[WebUIConfig] = None


@dataclass
class SkillsConfig:
    shared_dir: str = "./skills"
    sync_on_start: bool = True


@dataclass
class ConfigV2:
    peers: dict[str, PeerConfig] = field(default_factory=dict)
    bot: BotConfig = field(default_factory=BotConfig)
    default_mode: str = "auto"
    tool_batch_size: int = 15
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    daemon: DaemonConfig = field(default_factory=DaemonConfig)


# ─── Loaders ───


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
        ssh_port=data.get("ssh_port", 22),
        proxy_jump=data.get("proxy_jump"),
        proxy_command=data.get("proxy_command"),
        password=data.get("password"),
        daemon_port=data.get("daemon_port", 9100),
        node_path=data.get("node_path"),
        default_paths=data.get("default_paths", []),
    )


def _parse_bot(raw: dict[str, Any]) -> BotConfig:
    """Parse bot section."""
    bot = BotConfig()

    discord_raw = raw.get("discord")
    if discord_raw:
        bot.discord = DiscordBotConfig(
            token=discord_raw.get("token", ""),
            allowed_channels=[int(c) for c in discord_raw.get("allowed_channels", [])],
            command_prefix=discord_raw.get("command_prefix", "/"),
            admin_users=[int(u) for u in discord_raw.get("admin_users", [])],
        )

    telegram_raw = raw.get("telegram")
    if telegram_raw:
        bot.telegram = TelegramBotConfig(
            token=telegram_raw.get("token", ""),
            allowed_users=[int(u) for u in telegram_raw.get("allowed_users", [])],
            admin_users=[int(u) for u in telegram_raw.get("admin_users", [])],
            allowed_chats=[int(c) for c in telegram_raw.get("allowed_chats", [])],
        )

    webui_raw = raw.get("webui")
    if webui_raw:
        bot.webui = WebUIConfig(
            enabled=webui_raw.get("enabled", False),
            port=webui_raw.get("port", 8080),
            host=webui_raw.get("host", "127.0.0.1"),
        )

    return bot


def load_config_v2(config_path: str) -> ConfigV2:
    """Load and parse a v2 config file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path) as f:
        raw_data: dict[str, Any] = yaml.safe_load(f)

    if not raw_data:
        raise ValueError("Config file is empty")

    # Expand env vars throughout
    raw: dict[str, Any] = _process_value(raw_data)

    cfg = ConfigV2()

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
    cfg.tool_batch_size = int(raw.get("tool_batch_size", 15))

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
        cfg.daemon = DaemonConfig(
            install_dir=daemon_raw.get("install_dir", "~/.codecast/daemon"),
            auto_deploy=daemon_raw.get("auto_deploy", True),
            log_file=daemon_raw.get("log_file", "~/.codecast/daemon.log"),
        )

    return cfg


# ─── V1 Migration ───


def _is_localhost_host(host: str) -> bool:
    """Check if a host string refers to localhost (simple check for migration)."""
    return host.lower() in ("localhost", "127.0.0.1", "::1")


def migrate_v1_to_v2(v1_config_path: str) -> ConfigV2:
    """Migrate a v1 config (machines) to v2 format (peers).

    Transport auto-detection:
    - If machine has localhost: true or host is localhost/127.0.0.1 -> "local"
    - Otherwise -> "ssh"
    """
    path = Path(v1_config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {v1_config_path}")

    with open(path) as f:
        raw_data: dict[str, Any] = yaml.safe_load(f)

    if not raw_data:
        raise ValueError("Config file is empty")

    raw: dict[str, Any] = _process_value(raw_data)

    cfg = ConfigV2()

    # Migrate machines -> peers
    machines_raw: dict[str, Any] = raw.get("machines", {})
    for machine_id, md in (machines_raw or {}).items():
        md = md or {}
        host = md.get("host", machine_id)
        is_local = md.get("localhost", False) or _is_localhost_host(host)

        transport = "local" if is_local else "ssh"

        peer = PeerConfig(
            id=machine_id,
            transport=transport,
            ssh_host=host if transport == "ssh" else None,
            ssh_user=md.get("user") if transport == "ssh" else None,
            ssh_key=expand_path(md["ssh_key"]) if "ssh_key" in md and transport == "ssh" else None,
            ssh_port=md.get("port", 22),
            proxy_jump=md.get("proxy_jump"),
            proxy_command=md.get("proxy_command"),
            password=md.get("password"),
            daemon_port=md.get("daemon_port", 9100),
            node_path=md.get("node_path"),
            default_paths=md.get("default_paths", []),
        )
        cfg.peers[machine_id] = peer

    # Carry over bot config
    bot_raw: dict[str, Any] = raw.get("bot", {})
    if bot_raw:
        cfg.bot = _parse_bot(bot_raw)

    # Scalar settings
    cfg.default_mode = raw.get("default_mode", "auto")
    cfg.tool_batch_size = int(raw.get("tool_batch_size", 15))

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
        cfg.daemon = DaemonConfig(
            install_dir=daemon_raw.get("install_dir", "~/.codecast/daemon"),
            auto_deploy=daemon_raw.get("auto_deploy", True),
            log_file=daemon_raw.get("log_file", "~/.codecast/daemon.log"),
        )

    return cfg


# ─── Save ───


def save_config_v2(cfg: ConfigV2, config_path: str) -> None:
    """Save a ConfigV2 to a YAML file."""
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

    path = Path(config_path)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Saved v2 config to {config_path}")
