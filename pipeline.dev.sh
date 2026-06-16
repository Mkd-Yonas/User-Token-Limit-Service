#!/usr/bin/env bash
set -euo pipefail

# default = local
TARGET_ENV="${1:-local}"
SERVICE_NAME="keural-tqs"

ROOT_DIR="${WORKSPACE:-$(pwd)}"
BUILD_DIR="$ROOT_DIR"

IMAGE_NAME="$SERVICE_NAME"
CONTAINER_NAME="$SERVICE_NAME"

ENV_FILE="$BUILD_DIR/.env.dev"
DOCKER_NETWORK_OPT="--network keural-network"

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: no .env file for name: $ENV_FILE"
    exit 1
fi

echo "Service     : $SERVICE_NAME"
echo "Build Dir   : $BUILD_DIR"
echo "Image Name  : $IMAGE_NAME"
echo ""

cd "$BUILD_DIR"

echo "Docker build..."
docker build -t "$IMAGE_NAME" .

echo ""
echo "Stop & Remove old docker container..."

docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm   "$CONTAINER_NAME" 2>/dev/null || true

echo ""
echo "run new docker container..."

docker run -d \
  --name "$CONTAINER_NAME" \
  --env-file "$ENV_FILE" \
  -p 8002:8000 \
  --init \
  --restart unless-stopped \
  $DOCKER_NETWORK_OPT \
  "$IMAGE_NAME"

echo ""
echo "distributed complete - $SERVICE_NAME ($TARGET_ENV)"
