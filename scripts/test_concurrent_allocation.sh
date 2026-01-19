#!/bin/bash
# Test concurrent allocations for same game_id
# Validates that FOR UPDATE SKIP LOCKED prevents race conditions
#
# This test verifies the fix for PR review issue #1:
# Multiple concurrent allocation requests for the same game_id should
# all receive the same port, not different ports due to a race condition.
#
# Prerequisites:
#   - Docker services running (docker-compose up -d)
#   - curl and jq installed
#
# Usage:
#   ./scripts/test_concurrent_allocation.sh [base_url]
#
# Example:
#   ./scripts/test_concurrent_allocation.sh http://localhost:8080

set -e

BASE_URL="${1:-http://localhost:8080}"
GAME_ID="race-test-$(date +%s)"
RESULTS_FILE="/tmp/race_results_$$.txt"
CONCURRENT_REQUESTS=10

# Cleanup function
cleanup() {
    rm -f "$RESULTS_FILE"
}
trap cleanup EXIT

# Initialize results file
> "$RESULTS_FILE"

echo "============================================"
echo "Concurrent Allocation Race Condition Test"
echo "============================================"
echo ""
echo "Configuration:"
echo "  Base URL:    $BASE_URL"
echo "  Game ID:     $GAME_ID"
echo "  Concurrent:  $CONCURRENT_REQUESTS requests"
echo ""

# Check if server is reachable
echo "Checking server availability..."
if ! curl -s --connect-timeout 5 "$BASE_URL" > /dev/null 2>&1; then
    echo "ERROR: Cannot connect to $BASE_URL"
    echo "Make sure the server is running (docker-compose up -d)"
    exit 1
fi
echo "Server is reachable."
echo ""

# Launch concurrent requests
echo "Launching $CONCURRENT_REQUESTS concurrent allocation requests..."
for i in $(seq 1 $CONCURRENT_REQUESTS); do
    (
        result=$(curl -s -X POST "$BASE_URL/freeciv-web/meta/allocate?type=multiplayer&game_id=$GAME_ID" 2>&1)
        port=$(echo "$result" | jq -r '.port // "error"' 2>/dev/null || echo "parse_error")
        echo "$port" >> "$RESULTS_FILE"
    ) &
done

# Wait for all requests to complete
wait

echo "All requests completed."
echo ""

# Analyze results
UNIQUE_PORTS=$(sort "$RESULTS_FILE" | uniq | wc -l | tr -d ' ')
FIRST_PORT=$(head -1 "$RESULTS_FILE")
ALL_PORTS=$(cat "$RESULTS_FILE" | tr '\n' ' ')

echo "Results:"
echo "  Ports received: $ALL_PORTS"
echo "  Unique ports:   $UNIQUE_PORTS"
echo ""

# Check for errors
ERROR_COUNT=$(grep -c "error\|parse_error" "$RESULTS_FILE" || true)
if [ "$ERROR_COUNT" -gt 0 ]; then
    echo "WARNING: $ERROR_COUNT requests returned errors"
    echo ""
fi

# Evaluate test result
if [ "$UNIQUE_PORTS" -eq 1 ] && [ "$FIRST_PORT" != "error" ] && [ "$FIRST_PORT" != "parse_error" ]; then
    echo "============================================"
    echo "PASS: All $CONCURRENT_REQUESTS requests received same port ($FIRST_PORT)"
    echo "============================================"
    echo ""

    # Cleanup: Release the allocated port
    echo "Cleaning up: Releasing port $FIRST_PORT..."
    release_result=$(curl -s -X POST "$BASE_URL/freeciv-web/meta/release" -d "host=localhost&port=$FIRST_PORT" 2>&1)
    echo "Release response: $release_result"

    exit 0
else
    echo "============================================"
    echo "FAIL: Race condition detected!"
    echo "============================================"
    echo ""
    echo "Port distribution:"
    sort "$RESULTS_FILE" | uniq -c
    echo ""
    echo "Expected: All requests should receive the same port."
    echo "This indicates the FOR UPDATE SKIP LOCKED fix may not be working."

    exit 1
fi
