#!/bin/bash
# deploy-all-in-one.sh - Deploy the all-in-one image in air-gapped environment
# Run this script in the air-gapped environment after transferring the image

set -e

echo "🔒 Deploying Auxilium Manus All-in-One in Air-Gapped Environment"
echo "================================================================"

IMAGE_NAME="auxilium-manus"
IMAGE_TAG="all-in-one"
FULL_IMAGE_NAME="${IMAGE_NAME}:${IMAGE_TAG}"
CONTAINER_NAME="auxilium-manus"

COMPRESSED_FILE="docker/airgap-artifacts/${IMAGE_NAME}-${IMAGE_TAG}.tar.gz"
UNCOMPRESSED_FILE="docker/airgap-artifacts/${IMAGE_NAME}-${IMAGE_TAG}.tar"

if [[ -f "$COMPRESSED_FILE" ]]; then
    echo "📦 Found compressed image: $COMPRESSED_FILE"
    echo "🗜️ Decompressing image..."
    gunzip "$COMPRESSED_FILE"
    IMAGE_FILE="$UNCOMPRESSED_FILE"
elif [[ -f "$UNCOMPRESSED_FILE" ]]; then
    echo "📦 Found image: $UNCOMPRESSED_FILE"
    IMAGE_FILE="$UNCOMPRESSED_FILE"
else
    echo "❌ Error: No image file found!"
    echo "   Expected: $COMPRESSED_FILE or $UNCOMPRESSED_FILE"
    exit 1
fi

echo "📏 Image file size: $(du -h "$IMAGE_FILE" | cut -f1)"

echo ""
echo "📥 Loading Docker image..."
docker load -i "$IMAGE_FILE"

if ! docker images | grep -q "$IMAGE_NAME.*$IMAGE_TAG"; then
    echo "❌ Error: Image not found after loading"
    exit 1
fi

echo "📋 Loaded image details:"
docker images "$FULL_IMAGE_NAME" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"

echo ""
echo "🚀 Starting Auxilium Manus container..."

if docker ps -a | grep -q "$CONTAINER_NAME"; then
    echo "🔄 Stopping existing container..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
fi

docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    -p 3000:3000 \
    -p 8000:8000 \
    -v auxilium-manus-data:/app/data \
    "$FULL_IMAGE_NAME"

echo ""
echo "⏳ Waiting for services to start..."
sleep 10

if docker ps | grep -q "$CONTAINER_NAME"; then
    echo "✅ Container is running successfully!"
    echo ""
    echo "📊 Container Status:"
    docker ps --filter "name=$CONTAINER_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    echo ""
    echo "🌐 Access URLs:"
    echo "   Frontend: http://localhost:3000"
    echo "   Backend API: http://localhost:8000"
    echo "   Health Check: http://localhost:8000/health"
    echo ""
    echo "📋 Useful Commands:"
    echo "   View logs: docker logs $CONTAINER_NAME"
    echo "   Follow logs: docker logs -f $CONTAINER_NAME"
    echo "   Stop: docker stop $CONTAINER_NAME"
    echo "   Restart: docker restart $CONTAINER_NAME"
    echo "   Shell access: docker exec -it $CONTAINER_NAME /bin/bash"
    echo ""
    echo "⚠️  Configure runtime environment variables for production:"
    echo "   SECRET_KEY, INITIAL_PASSWORD, DATABASE_*, MANUS_REDIS_*, HATCHET_CLIENT_TOKEN"
else
    echo "❌ Container failed to start!"
    docker logs "$CONTAINER_NAME" 2>&1 || echo "No logs available"
    exit 1
fi

echo ""
echo "🎉 Auxilium Manus All-in-One Deployment Complete!"
