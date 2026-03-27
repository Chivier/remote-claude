#!/usr/bin/env bash
# deploy-test.sh — Build and deploy codecast to a remote test environment.
#
# Usage:
#   ./scripts/deploy-test.sh [SSH_HOST] [REMOTE_VENV]
#
# Defaults:
#   SSH_HOST    = artoria
#   REMOTE_VENV = /home/chivier/.venvs/default
#
# What it does:
#   1. Build Python sdist (source distribution) locally
#   2. SCP the tarball to the remote machine
#   3. pip install it into the remote venv (with --force-reinstall)
#   4. Optionally build + deploy the Rust daemon binary
#   5. Print installed version for verification
#
# Requires: ssh access to SSH_HOST, Python build tools locally (pip, build)

set -euo pipefail

# ─── Config ───
SSH_HOST="${1:-artoria}"
REMOTE_VENV="${2:-/home/chivier/.venvs/default}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$PROJECT_DIR/dist"
REMOTE_TMP="/tmp/codecast-deploy-$$"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}==>${NC} $*"; }
warn()  { echo -e "${YELLOW}==>${NC} $*"; }
error() { echo -e "${RED}==>${NC} $*" >&2; }

# ─── Step 1: Build sdist ───
info "Building Python source distribution..."
cd "$PROJECT_DIR"

# Clean old dist
rm -rf "$DIST_DIR"

python -m build --sdist --outdir "$DIST_DIR" 2>&1 | tail -3

# Find the built tarball
TARBALL=$(ls -1 "$DIST_DIR"/codecast-*.tar.gz 2>/dev/null | head -1)
if [ -z "$TARBALL" ]; then
    error "Build failed: no tarball found in $DIST_DIR"
    exit 1
fi

VERSION=$(basename "$TARBALL" | sed 's/codecast-//;s/\.tar\.gz//')
info "Built: $(basename "$TARBALL") (v$VERSION)"

# ─── Step 2: Upload to remote ───
info "Uploading to $SSH_HOST..."
ssh "$SSH_HOST" "mkdir -p $REMOTE_TMP"
scp -q "$TARBALL" "$SSH_HOST:$REMOTE_TMP/"

# ─── Step 3: Install on remote ───
info "Installing on $SSH_HOST into $REMOTE_VENV..."
REMOTE_TARBALL="$REMOTE_TMP/$(basename "$TARBALL")"
ssh "$SSH_HOST" "
    set -e
    source '$REMOTE_VENV/bin/activate'
    pip install --force-reinstall --no-deps '$REMOTE_TARBALL' 2>&1 | tail -5
    rm -rf '$REMOTE_TMP'
"

# ─── Step 4: Optionally deploy daemon binary ───
if [ "${DEPLOY_DAEMON:-0}" = "1" ]; then
    info "Building and deploying daemon binary..."

    # Build release binary
    cargo build --release 2>&1 | tail -3

    DAEMON_BIN="$PROJECT_DIR/target/release/codecast-daemon"
    if [ ! -f "$DAEMON_BIN" ]; then
        warn "Daemon binary not found at $DAEMON_BIN, skipping daemon deploy"
    else
        ssh "$SSH_HOST" "mkdir -p ~/.codecast/daemon"
        scp -q "$DAEMON_BIN" "$SSH_HOST:~/.codecast/daemon/codecast-daemon"
        ssh "$SSH_HOST" "chmod +x ~/.codecast/daemon/codecast-daemon"
        REMOTE_DAEMON_VER=$(ssh "$SSH_HOST" "~/.codecast/daemon/codecast-daemon --version 2>/dev/null || echo 'unknown'")
        info "Daemon deployed: $REMOTE_DAEMON_VER"
    fi
fi

# ─── Step 5: Verify ───
info "Verifying installation..."
REMOTE_VER=$(ssh "$SSH_HOST" "source '$REMOTE_VENV/bin/activate' && python -c 'from head.__version__ import __version__; print(__version__)' 2>/dev/null || echo 'FAILED'")

if [ "$REMOTE_VER" = "FAILED" ]; then
    error "Verification failed: could not import head.__version__"
    exit 1
fi

echo ""
info "Deployed codecast v$REMOTE_VER to $SSH_HOST:$REMOTE_VENV"
echo ""
echo "  Run tests:  ssh $SSH_HOST 'source $REMOTE_VENV/bin/activate && cd /tmp && python -m pytest'"
echo "  Start:      ssh $SSH_HOST 'source $REMOTE_VENV/bin/activate && codecast start'"
echo ""
