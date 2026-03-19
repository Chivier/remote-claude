#!/usr/bin/env bash
set -euo pipefail

# Codecast - One-line installer
# Usage: curl -fsSL https://raw.githubusercontent.com/Chivier/codecast/main/scripts/install.sh | bash

REPO="https://github.com/Chivier/codecast.git"
INSTALL_DIR="${CODECAST_DIR:-$HOME/.local/share/codecast}"
CONFIG_DIR="$HOME/.codecast"
VENV_DIR="$INSTALL_DIR/.venv"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# --- Pre-flight checks ---

check_command() {
    if ! command -v "$1" &>/dev/null; then
        error "$1 is required but not installed. $2"
    fi
}

info "Checking prerequisites..."

check_command git "Install git: https://git-scm.com/"
check_command python3 "Install Python 3.11+: https://www.python.org/"

# Check Python version >= 3.11
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
    error "Python 3.11+ required, found $PYTHON_VERSION"
fi
ok "Python $PYTHON_VERSION"

# Optional: check for Rust (needed only if building the daemon from source)
if command -v cargo &>/dev/null; then
    ok "Rust toolchain found (for building daemon)"
else
    warn "Rust not found. The head node will work, but to build the daemon binary you need Rust."
    warn "Install Rust: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
fi

# --- Clone or update repo ---

if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation at $INSTALL_DIR..."
    git -C "$INSTALL_DIR" pull --ff-only
    ok "Updated to latest"
else
    if [ -d "$INSTALL_DIR" ] && [ "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
        warn "$INSTALL_DIR exists and is not empty. Backing up to ${INSTALL_DIR}.bak"
        mv "$INSTALL_DIR" "${INSTALL_DIR}.bak.$(date +%s)"
    fi
    info "Cloning codecast to $INSTALL_DIR..."
    git clone "$REPO" "$INSTALL_DIR"
    ok "Cloned"
fi

# --- Create virtual environment and install ---

info "Setting up Python virtual environment..."
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

info "Installing codecast and dependencies..."
pip install --upgrade pip --quiet
pip install -e "$INSTALL_DIR" --quiet
ok "Installed"

# --- Build daemon if Rust is available ---

if command -v cargo &>/dev/null && [ -f "$INSTALL_DIR/Cargo.toml" ]; then
    info "Building Rust daemon..."
    (cd "$INSTALL_DIR" && cargo build --release --quiet)
    # Copy daemon binary to head/bin for deployment
    DAEMON_BIN="$INSTALL_DIR/target/release/codecast-daemon"
    if [ -f "$DAEMON_BIN" ]; then
        ARCH=$(uname -m)
        OS=$(uname -s | tr '[:upper:]' '[:lower:]')
        cp "$DAEMON_BIN" "$INSTALL_DIR/src/head/bin/codecast-daemon-${OS}-${ARCH}"
        ok "Daemon binary built and staged for deployment"
    fi
else
    warn "Skipping daemon build (Rust not available or no Cargo.toml)."
    warn "You can build it later: cd $INSTALL_DIR && cargo build --release"
fi

# --- Setup config ---

mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    cp "$INSTALL_DIR/config.example.yaml" "$CONFIG_DIR/config.yaml"
    info "Config template copied to $CONFIG_DIR/config.yaml"
    warn "Edit $CONFIG_DIR/config.yaml with your machines and bot token before starting."
else
    ok "Config already exists at $CONFIG_DIR/config.yaml"
fi

# --- Create wrapper script ---

WRAPPER="$HOME/.local/bin/codecast"
mkdir -p "$(dirname "$WRAPPER")"
cat > "$WRAPPER" <<SCRIPT
#!/usr/bin/env bash
source "$VENV_DIR/bin/activate"
exec python -m head.main "\$@"
SCRIPT
chmod +x "$WRAPPER"
ok "CLI command installed: $WRAPPER"

# --- Check PATH ---

if ! echo "$PATH" | tr ':' '\n' | grep -q "$HOME/.local/bin"; then
    warn "~/.local/bin is not in your PATH. Add this to your shell profile:"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# --- Done ---

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN} Codecast installed successfully!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit your config:  \$EDITOR $CONFIG_DIR/config.yaml"
echo "  2. Start the bot:     codecast"
echo ""
echo "Docs: https://github.com/Chivier/codecast#documentation"
