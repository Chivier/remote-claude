"""Tests for config v2 parser with peer model and v1 migration."""

import os
import textwrap
from pathlib import Path

import pytest
import yaml

from head.config import (
    BotConfig,
    Config,
    DaemonDeployConfig,
    DiscordConfig,
    PeerConfig,
    SkillsConfig,
    TelegramConfig,
    WebUIConfig,
    load_config_v2,
    migrate_v1_to_v2,
    save_config_v2,
)


# ─── Helpers ───


def _write_yaml(tmp_path: Path, content: str) -> Path:
    """Write a YAML string to a temp file and return its path."""
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(content))
    return p


# ─── load_config_v2 ───


class TestLoadMinimalConfig:
    """Load a minimal v2 config with an HTTP peer."""

    def test_loads_http_peer(self, tmp_path):
        p = _write_yaml(
            tmp_path,
            """\
            peers:
              gpu-1:
                transport: http
                address: https://gpu1.example.com:9100
                token: secret123
            """,
        )
        cfg = load_config_v2(str(p))
        assert "gpu-1" in cfg.peers
        peer = cfg.peers["gpu-1"]
        assert peer.id == "gpu-1"
        assert peer.transport == "http"
        assert peer.address == "https://gpu1.example.com:9100"
        assert peer.token == "secret123"

    def test_defaults_populated(self, tmp_path):
        p = _write_yaml(
            tmp_path,
            """\
            peers:
              web:
                transport: http
                address: https://example.com:9100
            """,
        )
        cfg = load_config_v2(str(p))
        peer = cfg.peers["web"]
        assert peer.daemon_port == 9100
        assert peer.default_paths == []
        assert peer.ssh_host is None
        assert peer.tls_fingerprint is None


class TestLoadSSHPeer:
    """Load an SSH peer including ProxyJump."""

    def test_ssh_peer_full(self, tmp_path):
        p = _write_yaml(
            tmp_path,
            """\
            peers:
              gpu-2:
                transport: ssh
                ssh_host: gpu2.lab.internal
                ssh_user: alice
                ssh_key: ~/.ssh/id_ed25519
                ssh_port: 2222
                proxy_jump: bastion
                daemon_port: 9200
                default_paths:
                  - /home/alice/project-a
            """,
        )
        cfg = load_config_v2(str(p))
        peer = cfg.peers["gpu-2"]
        assert peer.transport == "ssh"
        assert peer.ssh_host == "gpu2.lab.internal"
        assert peer.ssh_user == "alice"
        assert peer.ssh_port == 2222
        assert peer.proxy_jump == "bastion"
        assert peer.daemon_port == 9200
        assert peer.default_paths == ["/home/alice/project-a"]
        # ssh_key should be expanded
        assert "~" not in (peer.ssh_key or "")

    def test_ssh_peer_defaults(self, tmp_path):
        p = _write_yaml(
            tmp_path,
            """\
            peers:
              simple:
                transport: ssh
                ssh_host: simple.example.com
                ssh_user: bob
            """,
        )
        cfg = load_config_v2(str(p))
        peer = cfg.peers["simple"]
        assert peer.ssh_port == 22
        assert peer.proxy_jump is None
        assert peer.proxy_command is None


class TestLoadWithBotConfig:
    """Load config with bot settings."""

    def test_discord_and_telegram(self, tmp_path):
        p = _write_yaml(
            tmp_path,
            """\
            peers:
              local:
                transport: local
            bot:
              discord:
                token: disc-tok
                allowed_channels:
                  - 111
                  - 222
                admin_users:
                  - 999
              telegram:
                token: tg-tok
                allowed_users:
                  - 42
                admin_users:
                  - 43
                allowed_chats:
                  - 100
            """,
        )
        cfg = load_config_v2(str(p))
        assert cfg.bot.discord is not None
        assert cfg.bot.discord.token == "disc-tok"
        assert cfg.bot.discord.allowed_channels == [111, 222]
        assert cfg.bot.discord.admin_users == [999]

        assert cfg.bot.telegram is not None
        assert cfg.bot.telegram.token == "tg-tok"
        assert cfg.bot.telegram.allowed_users == [42]
        assert cfg.bot.telegram.admin_users == [43]
        assert cfg.bot.telegram.allowed_chats == [100]

    def test_webui_config(self, tmp_path):
        p = _write_yaml(
            tmp_path,
            """\
            peers:
              local:
                transport: local
            bot:
              webui:
                enabled: true
                port: 8080
                host: 0.0.0.0
            """,
        )
        cfg = load_config_v2(str(p))
        assert cfg.bot.webui is not None
        assert cfg.bot.webui.enabled is True
        assert cfg.bot.webui.port == 8080
        assert cfg.bot.webui.host == "0.0.0.0"


class TestEmptyConfig:
    """Handle empty or minimal config files."""

    def test_empty_file_raises(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("")
        with pytest.raises(ValueError, match="empty"):
            load_config_v2(str(p))

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config_v2(str(tmp_path / "nonexistent.yaml"))

    def test_no_peers_gives_empty_dict(self, tmp_path):
        p = _write_yaml(
            tmp_path,
            """\
            default_mode: plan
            """,
        )
        cfg = load_config_v2(str(p))
        assert cfg.peers == {}
        assert cfg.default_mode == "plan"


class TestEnvVarExpansion:
    """${ENV_VAR} expansion in config values."""

    def test_expands_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "expanded_token_value")
        monkeypatch.setenv("MY_HOST", "my-gpu.example.com")
        p = _write_yaml(
            tmp_path,
            """\
            peers:
              gpu:
                transport: http
                address: https://${MY_HOST}:9100
                token: ${MY_TOKEN}
            """,
        )
        cfg = load_config_v2(str(p))
        peer = cfg.peers["gpu"]
        assert peer.address == "https://my-gpu.example.com:9100"
        assert peer.token == "expanded_token_value"

    def test_unset_env_var_left_as_is(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SURELY_UNSET_VAR_12345", raising=False)
        p = _write_yaml(
            tmp_path,
            """\
            peers:
              x:
                transport: http
                address: https://host:9100
                token: ${SURELY_UNSET_VAR_12345}
            """,
        )
        cfg = load_config_v2(str(p))
        assert cfg.peers["x"].token == "${SURELY_UNSET_VAR_12345}"


# ─── migrate_v1_to_v2 ───


class TestMigrateV1:
    """Migrate v1 machine configs to v2 peers."""

    def test_migrate_machines_to_peers(self, tmp_path):
        v1_yaml = _write_yaml(
            tmp_path,
            """\
            machines:
              gpu-1:
                host: gpu1.example.com
                user: alice
                ssh_key: ~/.ssh/id_rsa
                port: 22
                proxy_jump: bastion
                daemon_port: 9100
                node_path: /usr/bin/node
                default_paths:
                  - /home/alice/project
            bot:
              discord:
                token: tok123
            default_mode: auto
            tool_batch_size: 15
            """,
        )
        cfg = migrate_v1_to_v2(str(v1_yaml))
        # Machine becomes an SSH peer
        assert "gpu-1" in cfg.peers
        peer = cfg.peers["gpu-1"]
        assert peer.transport == "ssh"
        assert peer.ssh_host == "gpu1.example.com"
        assert peer.ssh_user == "alice"
        assert peer.proxy_jump == "bastion"
        assert peer.daemon_port == 9100
        assert peer.node_path == "/usr/bin/node"
        assert peer.default_paths == ["/home/alice/project"]

        # Bot config carried over
        assert cfg.bot.discord is not None
        assert cfg.bot.discord.token == "tok123"

        # Other settings
        assert cfg.default_mode == "auto"
        assert cfg.tool_batch_size == 15

    def test_migrate_localhost_machine(self, tmp_path):
        v1_yaml = _write_yaml(
            tmp_path,
            """\
            machines:
              local:
                host: localhost
                user: me
                daemon_port: 9200
                default_paths:
                  - /home/me/code
            """,
        )
        cfg = migrate_v1_to_v2(str(v1_yaml))
        peer = cfg.peers["local"]
        assert peer.transport == "local"
        # Local peer should still have daemon_port
        assert peer.daemon_port == 9200
        assert peer.default_paths == ["/home/me/code"]

    def test_migrate_127_0_0_1(self, tmp_path):
        """127.0.0.1 should also map to local transport."""
        v1_yaml = _write_yaml(
            tmp_path,
            """\
            machines:
              mybox:
                host: 127.0.0.1
                user: me
            """,
        )
        cfg = migrate_v1_to_v2(str(v1_yaml))
        assert cfg.peers["mybox"].transport == "local"

    def test_migrate_explicit_localhost_field(self, tmp_path):
        """If v1 has localhost: true, transport should be local."""
        v1_yaml = _write_yaml(
            tmp_path,
            """\
            machines:
              box:
                host: mybox.local
                user: me
                localhost: true
            """,
        )
        cfg = migrate_v1_to_v2(str(v1_yaml))
        assert cfg.peers["box"].transport == "local"


# ─── save_config_v2 ───


class TestSaveConfigV2:
    """Save a v2 config to YAML."""

    def test_round_trip(self, tmp_path):
        cfg = Config(
            peers={
                "gpu-1": PeerConfig(
                    id="gpu-1",
                    transport="ssh",
                    ssh_host="gpu1.example.com",
                    ssh_user="alice",
                    daemon_port=9100,
                ),
                "local": PeerConfig(
                    id="local",
                    transport="local",
                    daemon_port=9200,
                ),
            },
            default_mode="auto",
        )
        out = tmp_path / "out.yaml"
        save_config_v2(cfg, str(out))

        # Reload and verify
        loaded = load_config_v2(str(out))
        assert "gpu-1" in loaded.peers
        assert loaded.peers["gpu-1"].transport == "ssh"
        assert loaded.peers["gpu-1"].ssh_host == "gpu1.example.com"
        assert "local" in loaded.peers
        assert loaded.peers["local"].transport == "local"
        assert loaded.default_mode == "auto"

    def test_save_creates_file(self, tmp_path):
        cfg = Config()
        out = tmp_path / "new_config.yaml"
        assert not out.exists()
        save_config_v2(cfg, str(out))
        assert out.exists()


# ─── Miscellaneous ───


class TestLocalPeer:
    """Local transport peer."""

    def test_local_peer(self, tmp_path):
        p = _write_yaml(
            tmp_path,
            """\
            peers:
              local:
                transport: local
                daemon_port: 9200
                default_paths:
                  - ~/projects
            """,
        )
        cfg = load_config_v2(str(p))
        peer = cfg.peers["local"]
        assert peer.transport == "local"
        assert peer.daemon_port == 9200


class TestDaemonAndSkillsConfig:
    """Daemon and skills sections."""

    def test_daemon_config(self, tmp_path):
        p = _write_yaml(
            tmp_path,
            """\
            daemon:
              install_dir: ~/.codecast/daemon
              auto_deploy: false
              log_file: /var/log/daemon.log
            """,
        )
        cfg = load_config_v2(str(p))
        assert cfg.daemon.auto_deploy is False
        assert cfg.daemon.log_file == "/var/log/daemon.log"

    def test_skills_config(self, tmp_path):
        p = _write_yaml(
            tmp_path,
            """\
            skills:
              shared_dir: ./my-skills
              sync_on_start: false
            """,
        )
        cfg = load_config_v2(str(p))
        assert cfg.skills.shared_dir == "./my-skills"
        assert cfg.skills.sync_on_start is False
