#!/bin/bash
# Quick Docker build test script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null && pwd)"
FREECIV_DIR="${SCRIPT_DIR}/.."

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_status() {
    local status=$1
    local message=$2
    if [ "$status" = "ok" ]; then
        echo -e "${GREEN}✓${NC} $message"
    elif [ "$status" = "warn" ]; then
        echo -e "${YELLOW}⚠${NC} $message"
    else
        echo -e "${RED}✗${NC} $message"
    fi
}

echo "🐳 FreeCiv3D Docker Build Test"
echo "=============================="

cd "$FREECIV_DIR"

# Test 1: Check if Docker is available
if ! command -v docker &> /dev/null; then
    print_status "fail" "Docker not found"
    exit 1
fi
print_status "ok" "Docker available"

# Test 2: Build with cache (dependencies stage)
echo ""
echo "Building dependencies stage (should be fast if cached)..."
if docker build --target dependencies -t freeciv3d:deps .; then
    print_status "ok" "Dependencies stage built successfully"
else
    print_status "fail" "Dependencies stage build failed"
    exit 1
fi

# Test 3: Check if we can build just the runtime without FreeCiv compilation
echo ""
echo "Testing runtime build with SKIP_FREECIV_BUILD=true..."
if docker build --build-arg SKIP_FREECIV_BUILD=true --target runtime -t freeciv3d:runtime-test .; then
    print_status "ok" "Runtime stage built successfully (without FreeCiv compilation)"
else
    print_status "fail" "Runtime stage build failed"
    exit 1
fi

# Test 4: Verify Python dependencies are available
echo ""
echo "Testing Python dependencies in container..."
if docker run --rm freeciv3d:runtime-test python3 -c "import bcrypt, yaml; print('Python dependencies OK')"; then
    print_status "ok" "Python dependencies available"
else
    print_status "warn" "Some Python dependencies missing (may be installed at runtime)"
fi

# Test 5: Check if freeciv-proxy files are present
echo ""
echo "Testing freeciv-proxy files..."
if docker run --rm freeciv3d:runtime-test test -f /docker/freeciv-proxy/freeciv-proxy.py; then
    print_status "ok" "freeciv-proxy files present"
else
    print_status "fail" "freeciv-proxy files missing"
    exit 1
fi

print_status "ok" "All Docker build tests passed!"
echo ""
echo "Next steps:"
echo "  • For full build: docker-compose up --build"
echo "  • For development: docker-compose -f docker-compose.yml -f docker-compose.dev.yml up"
echo "  • To test LLM gateway: python3 tests/test_llm_websocket.py"