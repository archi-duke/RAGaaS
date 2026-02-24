#!/bin/bash

# Configuration
DOCKER_HUB_USER=$1

if [ -z "$DOCKER_HUB_USER" ]; then
    echo "❌ Error: Docker Hub username is required."
    echo "Usage: ./push_to_hub.sh <your-docker-hub-username>"
    exit 1
fi

# Multi-arch platforms
PLATFORMS="linux/amd64,linux/arm64"

echo "🐳 Docker Hub User: $DOCKER_HUB_USER"
echo "🌐 Target Platforms: $PLATFORMS"
echo "==========================================="
echo "🚀 Building and Pushing Multi-arch Images..."
echo "==========================================="

# Setup buildx builder if not exists
BUILDER_NAME="ragaas-builder"
if ! docker buildx inspect $BUILDER_NAME > /dev/null 2>&1; then
    echo "🔧 Creating new buildx builder..."
    docker buildx create --name $BUILDER_NAME --use
    docker buildx boot $BUILDER_NAME
else
    docker buildx use $BUILDER_NAME
fi

# Function to build and push
build_and_push() {
    local service_name=$1
    local dockerfile_path=$2
    local context_path=$3
    local image_name="ragaas-$service_name"

    echo ""
    echo "📦 Processing $service_name..."
    
    # Use buildx for multi-arch build and push directly
    docker buildx build --platform $PLATFORMS \
        -t "$DOCKER_HUB_USER/$image_name:latest" \
        -f "$dockerfile_path" \
        "$context_path" \
        --push

    if [ $? -eq 0 ]; then
        echo "✅ $service_name multi-arch image pushed successfully!"
    else
        echo "❌ $service_name Build Failed"
        exit 1
    fi
}

# 1. Backend
build_and_push "backend" "backend/Dockerfile" "backend"

# 2. Ingest Service
build_and_push "ingest" "ingest_service/Dockerfile" "ingest_service"

# 3. Frontend
# Frontend is simple React build + Nginx, perfect for multi-arch
build_and_push "frontend" "frontend/Dockerfile" "frontend"

echo ""
echo "✅ All multi-arch images successfully pushed to Docker Hub!"
echo "   - $DOCKER_HUB_USER/ragaas-backend:latest"
echo "   - $DOCKER_HUB_USER/ragaas-ingest:latest"
echo "   - $DOCKER_HUB_USER/ragaas-frontend:latest"
