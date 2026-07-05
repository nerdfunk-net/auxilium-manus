#!/bin/bash
# prepare-all-in-one.sh - Build complete self-contained image for air-gap deployment
# Run this script on a machine with internet access

set -e

echo "🚀 Building Auxilium Manus All-in-One Image for Air-Gap Deployment"
echo "=================================================================="

# Configuration
IMAGE_NAME="auxilium-manus"
IMAGE_TAG="all-in-one"
FULL_IMAGE_NAME="${IMAGE_NAME}:${IMAGE_TAG}"
OUTPUT_FILE="docker/airgap-artifacts/${IMAGE_NAME}-${IMAGE_TAG}.tar"

# Create output directory
mkdir -p docker/airgap-artifacts

echo "📦 Building complete self-contained image..."
echo "   Image: ${FULL_IMAGE_NAME}"
echo "   Output: ${OUTPUT_FILE}"

# Detect proxy environment variables and build proxy arguments
PROXY_ARGS=""
if [ -n "${HTTP_PROXY}" ]; then
    PROXY_ARGS="${PROXY_ARGS} --build-arg HTTP_PROXY=${HTTP_PROXY}"
    echo "   🌐 HTTP Proxy detected: ${HTTP_PROXY}"
fi

if [ -n "${HTTPS_PROXY}" ]; then
    PROXY_ARGS="${PROXY_ARGS} --build-arg HTTPS_PROXY=${HTTPS_PROXY}"
    echo "   🔒 HTTPS Proxy detected: ${HTTPS_PROXY}"
fi

if [ -n "${NO_PROXY}" ]; then
    PROXY_ARGS="${PROXY_ARGS} --build-arg NO_PROXY=${NO_PROXY}"
    echo "   🚫 No Proxy list detected: ${NO_PROXY}"
fi

if [ -n "${PROXY_ARGS}" ]; then
    echo "   📡 Using proxy configuration for Docker build"
else
    echo "   🌍 No proxy configuration detected - building with direct internet access"
fi
echo ""

# Build the all-in-one image with conditional proxy arguments
docker build -t "${FULL_IMAGE_NAME}" -f docker/Dockerfile.all-in-one . \
    --no-cache ${PROXY_ARGS}

echo ""
echo "💾 Saving image to tar file..."
docker save "${FULL_IMAGE_NAME}" -o "${OUTPUT_FILE}"

# Compress the image for smaller transfer
echo "🗜️ Compressing image for transfer..."
gzip -f "${OUTPUT_FILE}"
COMPRESSED_FILE="${OUTPUT_FILE}.gz"

echo ""
echo "✅ All-in-One Image Build Complete!"
echo "=================================="
echo ""
echo "📁 Transfer file: ${COMPRESSED_FILE}"
echo "📏 File size: $(du -h "${COMPRESSED_FILE}" | cut -f1)"
echo ""
echo "🔒 Air-Gap Deployment Instructions:"
echo "1. Transfer ${COMPRESSED_FILE} to your air-gapped environment"
echo "2. Run: gunzip $(basename "${COMPRESSED_FILE}")"
echo "3. Run: docker load -i $(basename "${OUTPUT_FILE}")"
echo "4. Run: docker run -d --name auxilium-manus \\"
echo "        -p 3000:3000 -p 8000:8000 \\"
echo "        -v auxilium-manus-data:/app/data \\"
echo "        ${FULL_IMAGE_NAME}"
echo ""
echo "🌐 Access URLs (after deployment):"
echo "   Frontend: http://localhost:3000"
echo "   Backend API: http://localhost:8000"
echo ""
echo "📋 Image Details:"
echo "=================="
docker images "${FULL_IMAGE_NAME}" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"

echo ""
echo "🔍 Image Layers:"
docker history "${FULL_IMAGE_NAME}" --format "table {{.CreatedBy}}\t{{.Size}}" --no-trunc=false

echo ""
echo "✨ Ready for air-gap deployment!"
