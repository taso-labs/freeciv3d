#!/bin/bash
# Validation script for port conflict solution

set -e

echo "========================================="
echo "Port Solution Validation"
echo "========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

TESTS_PASSED=0
TESTS_TOTAL=0

test_result() {
    TESTS_TOTAL=$((TESTS_TOTAL + 1))
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✓${NC} $2"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        echo -e "${RED}✗${NC} $2"
    fi
}

# Test 1: Container is running
echo "1. Checking container status..."
docker ps | grep -q fciv-net
test_result $? "Container 'fciv-net' is running"
echo ""

# Test 2: Game servers are listening (inside container)
echo "2. Checking game server ports (inside container)..."
docker exec fciv-net bash -c "ss -tln | grep -q ':6000 '"
test_result $? "Game server listening on port 6000"

docker exec fciv-net bash -c "ss -tln | grep -q ':6001 '"
test_result $? "Game server listening on port 6001"
echo ""

# Test 3: WebSocket proxies are listening (inside container on 7000+)
echo "3. Checking WebSocket proxy ports (inside container)..."
docker exec fciv-net bash -c "ss -tln | grep -q ':7000 '"
test_result $? "WebSocket proxy listening on container port 7000"

docker exec fciv-net bash -c "ss -tln | grep -q ':7001 '"
test_result $? "WebSocket proxy listening on container port 7001"
echo ""

# Test 4: Host port 7000 is NOT used by our container (avoiding macOS conflict)
echo "4. Checking host port remapping (7000 avoided)..."
# Check that host port 7100 is mapped (not 7000)
docker port fciv-net | grep -q "7000/tcp -> 0.0.0.0:7100"
test_result $? "WebSocket proxy correctly remapped to host port 7100"
echo ""

# Test 5: Metaserver is accessible
echo "5. Checking metaserver..."
docker exec fciv-net bash -c "curl -sf http://localhost:8080/freeciv-web/meta/status" > /dev/null
test_result $? "Metaserver status endpoint accessible"
echo ""

# Test 6: Servers are registered
echo "6. Checking server registration..."
STATUS=$(docker exec fciv-net bash -c "curl -s http://localhost:8080/freeciv-web/meta/status")
echo "   Metaserver status: $STATUS"

SERVER_COUNT=$(echo "$STATUS" | cut -d';' -f2)
if [ "$SERVER_COUNT" -ge 1 ]; then
    test_result 0 "At least 1 server registered (found: $SERVER_COUNT)"
else
    test_result 1 "At least 1 server registered (found: $SERVER_COUNT)"
fi
echo ""

# Test 7: civclientlauncher servlet works
echo "7. Checking civclientlauncher servlet..."
LAUNCHER_RESULT=$(docker exec fciv-net bash -c "curl -s -X POST 'http://localhost:8080/freeciv-web/civclientlauncher' -d 'action=new&type=singleplayer'")
if echo "$LAUNCHER_RESULT" | grep -q "success"; then
    test_result 0 "civclientlauncher returns 'success'"
else
    test_result 1 "civclientlauncher returns 'success' (got: $LAUNCHER_RESULT)"
fi
echo ""

# Test 8: Web interface is accessible
echo "8. Checking web interface..."
curl -sf "http://localhost:8080/freeciv-web/" | grep -iq "freeciv"
test_result $? "Web interface loads successfully"
echo ""

# Test 9: nginx is proxying correctly
echo "9. Checking nginx proxy configuration..."
docker exec fciv-net bash -c "curl -sf http://localhost/freeciv-web/" > /dev/null
test_result $? "nginx proxies to Tomcat correctly"
echo ""

# Test 10: Database connectivity
echo "10. Checking database..."
docker exec fciv-net bash -c "mysql -u docker -pchangeme freeciv_web -e 'SELECT 1' 2>/dev/null" > /dev/null
test_result $? "MySQL database accessible"
echo ""

# Summary
echo "========================================="
echo "Results: $TESTS_PASSED/$TESTS_TOTAL tests passed"
echo "========================================="
echo ""

if [ $TESTS_PASSED -eq $TESTS_TOTAL ]; then
    echo -e "${GREEN}All tests passed! ✓${NC}"
    echo ""
    echo "The port conflict solution is working correctly:"
    echo "  - Game servers: ports 6000-6009 (container)"
    echo "  - WebSocket proxies: ports 7000-7009 (container) → 7100-7109 (host)"
    echo "  - No conflict with macOS Control Center on port 7000"
    echo ""
    exit 0
else
    echo -e "${RED}Some tests failed. Please review the output above.${NC}"
    exit 1
fi

