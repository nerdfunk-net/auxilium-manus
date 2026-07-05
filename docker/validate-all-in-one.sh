#!/bin/bash
# validate-all-in-one.sh - Validate the all-in-one deployment

set -e

echo "🔍 Validating Auxilium Manus All-in-One Deployment"
echo "=================================================="

CONTAINER_NAME="auxilium-manus"
FRONTEND_URL="http://localhost:3000"
BACKEND_URL="http://localhost:8000"
HEALTH_URL="http://localhost:8000/health"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_status() {
    local status="$1"
    local message="$2"
    case "$status" in
        "pass") echo -e "${GREEN}✅ $message${NC}" ;;
        "fail") echo -e "${RED}❌ $message${NC}" ;;
        "warn") echo -e "${YELLOW}⚠️ $message${NC}" ;;
        *) echo "$message" ;;
    esac
}

echo "🐳 Checking Docker image..."
if docker images | grep -q "auxilium-manus.*all-in-one"; then
    print_status "pass" "Docker image found"
else
    print_status "fail" "Docker image not found"
    exit 1
fi

echo ""
echo "📦 Checking container status..."
if docker ps | grep -q "$CONTAINER_NAME"; then
    print_status "pass" "Container is running"
else
    print_status "fail" "Container is not running"
    if docker ps -a | grep -q "$CONTAINER_NAME"; then
        print_status "warn" "Container exists but is stopped"
        docker logs --tail 20 "$CONTAINER_NAME"
    fi
    exit 1
fi

echo ""
echo "🌐 Checking port bindings..."
PORTS=$(docker port "$CONTAINER_NAME")
if echo "$PORTS" | grep -q "3000"; then
    print_status "pass" "Frontend port 3000 is bound"
else
    print_status "fail" "Frontend port 3000 is not bound"
fi

if echo "$PORTS" | grep -q "8000"; then
    print_status "pass" "Backend port 8000 is bound"
else
    print_status "fail" "Backend port 8000 is not bound"
fi

echo ""
echo "🏥 Testing backend health endpoint..."
if curl -s --max-time 10 --connect-timeout 5 "$HEALTH_URL" >/dev/null 2>&1; then
    print_status "pass" "Backend health endpoint responding"
    HEALTH_RESPONSE=$(curl -s --max-time 5 "$HEALTH_URL" 2>/dev/null || echo "Failed to get response")
    echo "   Response: $HEALTH_RESPONSE"
else
    print_status "fail" "Backend health endpoint not responding"
fi

echo ""
echo "🎨 Testing frontend accessibility..."
if curl -s --max-time 10 --connect-timeout 5 "$FRONTEND_URL" >/dev/null 2>&1; then
    print_status "pass" "Frontend is accessible"
else
    print_status "warn" "Frontend not accessible (may still be starting)"
fi

echo ""
echo "💾 Checking data volume..."
if docker volume ls | grep -q "auxilium-manus-data"; then
    print_status "pass" "Data volume exists"
else
    print_status "warn" "Data volume not found (may be created on first run)"
fi

echo ""
echo "📋 Validation Summary"
echo "===================="
echo "Container: $CONTAINER_NAME"
echo "Image: auxilium-manus:all-in-one"
echo "Frontend URL: $FRONTEND_URL"
echo "Backend URL: $BACKEND_URL"

if docker ps | grep -q "$CONTAINER_NAME" && curl -s --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; then
    print_status "pass" "All critical tests passed!"
    exit 0
else
    print_status "warn" "Some tests failed - check the logs"
    exit 1
fi
