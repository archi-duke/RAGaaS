#!/bin/bash

# RAG Management System - Docker Image Import Script
# 폐쇄망 환경에서 Docker 이미지 로드 스크립트

set -e

echo "========================================="
echo "RAG Management System"
echo "Docker Image Import for Air-Gapped Deploy"
echo "========================================="
echo ""

# Docker 이미지 디렉토리 확인
IMAGE_DIR="docker-images"

if [ ! -d "$IMAGE_DIR" ]; then
    echo "Error: $IMAGE_DIR directory not found!"
    echo "Please ensure you have extracted the deployment package."
    exit 1
fi

# tar 파일 개수 확인
image_count=$(ls -1 "$IMAGE_DIR"/*.tar 2>/dev/null | wc -l)

if [ "$image_count" -eq 0 ]; then
    echo "Error: No .tar files found in $IMAGE_DIR"
    exit 1
fi

echo "Found $image_count Docker image(s) to load"
echo ""

echo "Step 1: Loading Docker images..."
echo "-----------------------------------"

current=0
for image_file in "$IMAGE_DIR"/*.tar; do
    current=$((current + 1))
    filename=$(basename "$image_file")
    
    echo "[$current/$image_count] Loading $filename..."
    
    if docker load -i "$image_file"; then
        echo "   ✓ Loaded successfully"
    else
        echo "   ✗ Failed to load $filename"
    fi
    echo ""
done

echo "Step 2: Verifying loaded images..."
echo "-----------------------------------"
docker images | grep -E "ragaas|milvus|etcd|minio|fuseki" || echo "Warning: Some images may not be loaded"
echo ""

echo "========================================="
echo "✓ Import Complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. Configure .env file with your settings"
echo "2. Run: docker-compose up -d"
echo "3. Access frontend at http://SERVER_IP"
echo ""
echo "For detailed instructions, see AIRGAP-DEPLOY.md"
echo ""
