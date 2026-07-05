#!/bin/bash

echo "=== Auxilium Manus Docker Deployment Test ==="
echo

echo "1. Checking container status..."
if docker ps | grep -q "auxilium-manus"; then
    echo "✅ Container is running"
else
    echo "❌ Container is not running"
    exit 1
fi

echo
echo "2. Testing backend health endpoint..."
BACKEND_HEALTH=$(curl -s http://localhost:8000/health)
if echo "$BACKEND_HEALTH" | grep -q "ok"; then
    echo "✅ Backend health check passed"
    echo "   Response: $BACKEND_HEALTH"
else
    echo "❌ Backend health check failed"
    exit 1
fi

echo
echo "3. Testing backend health via frontend proxy..."
PROXY_HEALTH=$(curl -s http://localhost:3000/api/proxy/health)
if echo "$PROXY_HEALTH" | grep -q "ok"; then
    echo "✅ Frontend proxy health check passed"
    echo "   Response: $PROXY_HEALTH"
else
    echo "❌ Frontend proxy health check failed"
    exit 1
fi

echo
echo "4. Testing frontend main page..."
FRONTEND_PAGE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000)
if [ "$FRONTEND_PAGE" = "200" ]; then
    echo "✅ Frontend main page accessible (HTTP $FRONTEND_PAGE)"
else
    echo "❌ Frontend main page not accessible (HTTP $FRONTEND_PAGE)"
    exit 1
fi

echo
echo "=== All tests passed! Auxilium Manus is running successfully in Docker ==="
echo
echo "Access the application at:"
echo "  Frontend: http://localhost:3000"
echo "  Backend API docs: http://localhost:3000/api/proxy/docs"
echo
