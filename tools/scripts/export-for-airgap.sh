#!/bin/bash

# RAG Management System - Docker Image Export Script
# 폐쇄망 배포를 위한 Docker 이미지 저장 스크립트

set -e

echo "========================================="
echo "RAG Management System"
echo "Docker Image Export for Air-Gapped Deploy"
echo "========================================="
echo ""

# 이미지 목록
IMAGES=(
    "ragaas-backend:latest"
    "ragaas-frontend:latest"
    "milvusdb/milvus:v2.3.3"
    "quay.io/coreos/etcd:v3.5.5"
    "minio/minio:RELEASE.2023-03-20T20-16-18Z"
    "stain/jena-fuseki:latest"
)

# 출력 디렉토리 생성
OUTPUT_DIR="docker-images"
mkdir -p "$OUTPUT_DIR"

echo "Step 1: Building local images..."
echo "-----------------------------------"
docker-compose build
echo ""

echo "Step 2: Pulling external images..."
echo "-----------------------------------"
docker-compose pull
echo ""

echo "Step 3: Saving images to tar files..."
echo "-----------------------------------"

total=${#IMAGES[@]}
current=0

for image in "${IMAGES[@]}"; do
    current=$((current + 1))
    echo "[$current/$total] Saving $image..."
    
    # 파일명 생성 (특수문자 제거)
    filename=$(echo "$image" | sed 's/:/_/g' | sed 's/\//_/g')
    output_file="$OUTPUT_DIR/${filename}.tar"
    
    # 이미지 저장
    if docker save -o "$output_file" "$image" 2>/dev/null; then
        size=$(du -sh "$output_file" | cut -f1)
        echo "   ✓ Saved: $output_file ($size)"
    else
        echo "   ✗ Failed to save $image (image may not exist)"
    fi
    echo ""
done

echo "Step 4: Creating deployment package..."
echo "-----------------------------------"

# 배포 패키지 디렉토리 생성
DEPLOY_DIR="ragaas-deploy"
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"

# 필수 파일 복사
echo "Copying application files..."
cp -r backend "$DEPLOY_DIR/"
cp -r frontend "$DEPLOY_DIR/"
cp docker-compose.yml "$DEPLOY_DIR/"
cp .env.example "$DEPLOY_DIR/.env"
cp AIRGAP-DEPLOY.md "$DEPLOY_DIR/"
cp README.md "$DEPLOY_DIR/"

# 불필요한 파일 제거
echo "Cleaning up unnecessary files..."
rm -rf "$DEPLOY_DIR/backend/venv"
rm -rf "$DEPLOY_DIR/backend/__pycache__"
rm -rf "$DEPLOY_DIR/backend/.pytest_cache"
rm -rf "$DEPLOY_DIR/backend/data"
rm -rf "$DEPLOY_DIR/frontend/node_modules"
rm -rf "$DEPLOY_DIR/frontend/dist"

# Docker 이미지 복사
echo "Copying Docker images..."
cp -r "$OUTPUT_DIR" "$DEPLOY_DIR/"

echo ""
echo "Step 5: Compressing deployment package..."
echo "-----------------------------------"

ARCHIVE_NAME="ragaas-deploy-$(date +%Y%m%d-%H%M%S).tar.gz"
tar -czf "$ARCHIVE_NAME" "$DEPLOY_DIR/"

package_size=$(du -sh "$ARCHIVE_NAME" | cut -f1)

echo ""
echo "========================================="
echo "✓ Export Complete!"
echo "========================================="
echo ""
echo "Deployment package: $ARCHIVE_NAME"
echo "Package size: $package_size"
echo ""
echo "Next steps:"
echo "1. Transfer $ARCHIVE_NAME to the air-gapped server"
echo "2. Follow instructions in AIRGAP-DEPLOY.md"
echo ""
echo "Files included:"
echo "  - Application code (backend, frontend)"
echo "  - Docker images (all dependencies)"
echo "  - Docker Compose configuration"
echo "  - Deployment guide"
echo ""
