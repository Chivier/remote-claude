# Getting Started

This guide walks you through setting up Codecast from scratch: installing the head node on your local machine, configuring at least one bot, and connecting your first remote machine.

## Prerequisites

Before you begin, make sure you have:

- **Local machine** (where you run the head node)
  - Python 3.11+
  - Rust toolchain (only if you want to build the daemon locally for development)
  - SSH access to your remote machine(s)
- **Remote machine(s)**
  - SSH server running
  - [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- **A bot token** — Discord, Telegram, or Lark

For normal usage, the remote machine does **not** need Node.js or npm. The daemon is a self-contained Rust binary.

---

## Step 1: Install Codecast

Recommended:

```bash
pip install codecast
```

For local development from source:

```bash
git clone https://github.com/Chivier/codecast.git
cd codecast
pip install -e .
```

If you need to build the daemon locally during development:

```bash
cargo build --release
```

---

## Step 2: Create Your Config File

Create the standard config location and copy the example file:

```bash
mkdir -p ~/.codecast
cp config.example.yaml ~/.codecast/config.yaml
```

The main sections you will edit are:

| Section | Purpose |
|---------|---------|
| `peers` | Remote machines Codecast can connect to |
| `bot` | Discord / Telegram / Lark bot credentials |
| `default_mode` | Permission mode for new sessions |
| `daemon` | Daemon settings such as bind/port behavior |

A minimal working example:

```yaml
peers:
  my-server:
    host: 192.168.1.100
    user: alice
    daemon_port: 9100
    default_paths:
      - /home/alice/myproject

bot:
  discord:
    token: ${DISCORD_TOKEN}
    allowed_channels:
      - 1234567890123456789

default_mode: auto
```

See [Configuration Guide](./en/configuration.md) and [Adding a Server](./adding-a-server.md) for the full schema.

---

## Step 3: Set Environment Variables

Export your bot tokens before running Codecast:

```bash
export DISCORD_TOKEN="your-discord-bot-token"
# and/or
export TELEGRAM_TOKEN="your-telegram-bot-token"
export LARK_APP_ID="your-lark-app-id"
export LARK_APP_SECRET="your-lark-app-secret"
```

---

## Step 4: Verify SSH Access

Make sure you can SSH into your remote machine without friction:

```bash
ssh alice@192.168.1.100 "echo SSH OK"
```

If this prompts for a password every time, set up SSH keys.

---

## Step 5: Verify Claude CLI on the Remote

SSH into the remote machine and confirm Claude CLI is installed and authenticated:

```bash
ssh alice@192.168.1.100
claude --version
claude
```

For a quick non-interactive smoke check you can also run:

```bash
claude -p "Hello" --output-format stream-json
```

---

## Step 6: Run Codecast

Start the head node:

```bash
codecast
```

Or use a specific config file:

```bash
codecast ~/.codecast/config.yaml
```

You should see log output indicating configured bots, peers, and default mode.

---

## Step 7: Start Your First Session

In your Discord / Telegram / Lark chat, run:

```
/start my-server /home/alice/myproject
```

Codecast will:

1. Open or reuse an SSH tunnel to `my-server`
2. Ensure the daemon binary is present and running on the remote machine
3. Sync runtime instruction/skill files if configured
4. Create a new AI session in `/home/alice/myproject`
5. Stream the response back to chat in real time

Once connected, just send plain text messages — they will be forwarded to the active session.

---

## What Happens on First Connect

When auto-deploy is enabled, the head node will:

1. Resolve the local daemon binary
2. Copy it to the remote machine (typically under `~/.codecast/daemon/`)
3. Start the daemon on the remote host
4. Wait for `health.check` to succeed

The remote machine only needs SSH and the target AI CLI installed. It does not need npm for the daemon.

---

## Next Steps

- [Adding a Discord Bot](./adding-a-discord-bot.md)
- [Adding a Server](./adding-a-server.md)
- [Commands Reference](./commands-reference.md)
