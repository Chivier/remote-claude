#!/usr/bin/env bash
set -euo pipefail

echo "=== Codecast Multi-User Integration Tests ==="

# ── 1. Start Alice's daemon (port 9100) ──
echo ""
echo "--- Starting Alice's daemon ---"
su - alice -c "DAEMON_PORT=9100 RUST_LOG=info codecast-daemon &" 2>&1

# Wait for Alice's daemon
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:9100/rpc \
        -X POST -H 'Content-Type: application/json' \
        -d '{"method":"health.check"}' > /dev/null 2>&1; then
        echo "  [OK] Alice's daemon ready on port 9100 (took ${i}s)"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "  [FAIL] Alice's daemon did not start within 30s"
        exit 1
    fi
    sleep 1
done

# ── 2. Start Bob's daemon (port 9100 taken → auto picks 9101) ──
echo ""
echo "--- Starting Bob's daemon ---"
su - bob -c "DAEMON_PORT=9100 RUST_LOG=info codecast-daemon &" 2>&1

# Wait for Bob's daemon (should be on 9101 due to auto-increment)
BOB_PORT=""
for i in $(seq 1 30); do
    # Try ports 9101-9110 (auto-increment)
    for p in $(seq 9101 9110); do
        if curl -sf "http://127.0.0.1:${p}/rpc" \
            -X POST -H 'Content-Type: application/json' \
            -d '{"method":"health.check"}' > /dev/null 2>&1; then
            BOB_PORT="$p"
            break 2
        fi
    done
    if [ "$i" -eq 30 ]; then
        echo "  [FAIL] Bob's daemon did not start within 30s"
        exit 1
    fi
    sleep 1
done
echo "  [OK] Bob's daemon ready on port ${BOB_PORT} (auto-incremented)"

# ── 3. Run pytest ──
echo ""
echo "--- Running multi-user tests ---"
TEST_EXIT=0
ALICE_PORT=9100 BOB_PORT="${BOB_PORT}" \
    python -m pytest tests/integration/test_multiuser.py -v --tb=short || TEST_EXIT=$?

# ── 4. Cleanup ──
echo ""
echo "--- Cleanup ---"
# Kill all daemon processes
pkill -f codecast-daemon 2>/dev/null || true
sleep 1
echo "  Daemons stopped"

exit $TEST_EXIT
