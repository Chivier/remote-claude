#!/usr/bin/env bash
# bump-version.sh — single-source version management
#
# Usage:
#   ./scripts/bump-version.sh 0.3.0      # set version
#   ./scripts/bump-version.sh             # show current version
#
# Source of truth: pyproject.toml [project].version
# Synced targets:  src/head/__version__.py, Cargo.toml

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

PYPROJECT="pyproject.toml"
VERSION_PY="src/head/__version__.py"
CARGO_TOML="Cargo.toml"

current=$(grep '^version = ' "$PYPROJECT" | head -1 | sed 's/version = "\(.*\)"/\1/')

if [ $# -eq 0 ]; then
    echo "$current"
    exit 0
fi

new="$1"

# Validate semver-ish format
if ! echo "$new" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$'; then
    echo "Error: '$new' is not a valid version (expected X.Y.Z)" >&2
    exit 1
fi

echo "Bumping version: $current → $new"

# 1. pyproject.toml (source of truth)
sed -i "s/^version = \"$current\"/version = \"$new\"/" "$PYPROJECT"

# 2. src/head/__version__.py
echo "__version__ = \"$new\"" > "$VERSION_PY"

# 3. Cargo.toml (first version = line only)
sed -i "0,/^version = \".*\"/s/^version = \".*\"/version = \"$new\"/" "$CARGO_TOML"

echo "Updated:"
echo "  $PYPROJECT      → $new"
echo "  $VERSION_PY     → $new"
echo "  $CARGO_TOML     → $new"
echo ""
echo "Next steps:"
echo "  git add -A && git commit -m 'chore: bump version to $new'"
echo "  git tag v$new && git push --tags"
