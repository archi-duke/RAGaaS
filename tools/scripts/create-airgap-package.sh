#!/bin/bash

# Air-gapped Deployment Package Creator
# Run this script in internet-connected environment

set -e

echo "========================================="
echo "RAGaaS Air-gapped Deployment Packager"
echo "========================================="

# Configuration
PACKAGE_NAME="ragaas-airgap-$(date +%Y%m%d-%H%M%S)"
PACKAGE_DIR="${PACKAGE_NAME}"

echo ""
echo "Creating package directory: ${PACKAGE_DIR}"
mkdir -p "${PACKAGE_DIR}"

# Step 1: Build Docker images
echo ""
echo "[1/5] Building Docker images..."
docker-compose build

# Step 2: Save Docker images
echo ""
echo "[2/5] Saving Docker images..."
mkdir -p "${PACKAGE_DIR}/docker-images"

IMAGES=(
  "ragaas-backend:latest"
  "ragaas-frontend:latest"
  "milvusdb/milvus:v2.3.3"
  "quay.io/coreos/etcd:v3.5.5"
  "minio/minio:RELEASE.2023-03-20T20-16-18Z"
)

for img in "${IMAGES[@]}"; do
  filename=$(echo $img | tr '/:' '_')
  echo "  Saving: ${filename}.tar"
  docker save $img -o "${PACKAGE_DIR}/docker-images/${filename}.tar"
done

# Step 3: Download local embedding model
echo ""
echo "[3/5] Downloading local embedding model..."
mkdir -p "${PACKAGE_DIR}/models"

# Check if sentence-transformers is installed
if ! python3 -c "import sentence_transformers" 2>/dev/null; then
    echo "  Installing sentence-transformers (required for model download)..."
    pip3 install sentence-transformers --quiet
fi

python3 << EOF
from sentence_transformers import SentenceTransformer
import os

model_path = '${PACKAGE_DIR}/models/all-MiniLM-L6-v2'
print(f"  Downloading model to: {model_path}")
model = SentenceTransformer('all-MiniLM-L6-v2')
model.save(model_path)
print("  Model downloaded successfully!")
EOF

# Step 4: Download Python dependencies
echo ""
echo "[4/5] Downloading Python dependencies..."
mkdir -p "${PACKAGE_DIR}/backend/wheels"
pip download -r backend/requirements.txt -d "${PACKAGE_DIR}/backend/wheels/"

# Step 5: Copy project files
echo ""
echo "[5/5] Copying project files..."
rsync -av --exclude='venv' \
          --exclude='__pycache__' \
          --exclude='node_modules' \
          --exclude='dist' \
          --exclude='.git' \
          --exclude='*.db' \
          --exclude='volumes' \
          backend/ "${PACKAGE_DIR}/backend/"

rsync -av --exclude='node_modules' \
          --exclude='dist' \
          --exclude='.git' \
          frontend/ "${PACKAGE_DIR}/frontend/"

# Copy deployment files
cp docker-compose.yml "${PACKAGE_DIR}/"
cp AIRGAP-DEPLOY.md "${PACKAGE_DIR}/"
cp DOCKER.md "${PACKAGE_DIR}/"

# Create docker-compose.airgap.yml
cat > "${PACKAGE_DIR}/docker-compose.airgap.yml" << 'EOFCOMPOSE'
version: '3.5'

services:
  etcd:
    container_name: milvus-etcd
    image: quay.io/coreos/etcd:v3.5.5
    environment:
      - ETCD_AUTO_COMPACTION_MODE=revision
      - ETCD_AUTO_COMPACTION_RETENTION=1000
      - ETCD_QUOTA_BACKEND_BYTES=4294967296
      - ETCD_SNAPSHOT_COUNT=50000
    volumes:
      - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/etcd:/etcd
    command: etcd -advertise-client-urls=http://127.0.0.1:2379 -listen-client-urls=http://0.0.0.0:2379 --data-dir /etcd
    restart: unless-stopped

  minio:
    container_name: milvus-minio
    image: minio/minio:RELEASE.2023-03-20T20-16-18Z
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    ports:
      - "9001:9001"
      - "9000:9000"
    volumes:
      - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/minio:/minio_data
    command: minio server /minio_data --console-address ":9001"
    restart: unless-stopped

  standalone:
    container_name: milvus-standalone
    image: milvusdb/milvus:v2.3.3
    command: ["milvus", "run", "standalone"]
    environment:
      ETCD_ENDPOINTS: etcd:2379
      MINIO_ADDRESS: minio:9000
      MINIO_ACCESS_KEY_ID: minioadmin
      MINIO_SECRET_KEY: minioadmin
    volumes:
      - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/milvus:/var/lib/milvus
    ports:
      - "19530:19530"
    depends_on:
      - etcd
      - minio
    restart: unless-stopped

  backend:
    container_name: ragaas-backend
    image: ragaas-backend:latest
    environment:
      - USE_LOCAL_MODEL=true
      - LOCAL_MODEL_PATH=/app/models/all-MiniLM-L6-v2
      - MILVUS_HOST=standalone
      - MILVUS_PORT=19530
      - DATABASE_URL=sqlite:////app/data/rag_system.db
    volumes:
      - ./backend/data:/app/data
      - ./models:/app/models:ro
    ports:
      - "8000:8000"
    depends_on:
      - standalone
    restart: unless-stopped

  frontend:
    container_name: ragaas-frontend
    image: ragaas-frontend:latest
    ports:
      - "80:80"
    depends_on:
      - backend
    restart: unless-stopped

networks:
  default:
    name: milvus
EOFCOMPOSE

# Create deployment script
cat > "${PACKAGE_DIR}/deploy.sh" << 'EOFDEPLOY'
#!/bin/bash
set -e

echo "========================================="
echo "RAGaaS Air-gapped Deployment"
echo "========================================="

# Load Docker images
echo ""
echo "Loading Docker images..."
for tarfile in docker-images/*.tar; do
  echo "  Loading $(basename $tarfile)..."
  docker load -i "$tarfile"
done

echo ""
echo "Starting services..."
docker-compose -f docker-compose.airgap.yml up -d

echo ""
echo "Waiting for services to be ready..."
sleep 10

echo ""
echo "========================================="
echo "Deployment complete!"
echo "========================================="
echo ""
echo "Access URLs:"
echo "  Frontend:  http://localhost"
echo "  Backend:   http://localhost:8000"
echo "  API Docs:  http://localhost:8000/docs"
echo ""
echo "Check status: docker-compose -f docker-compose.airgap.yml ps"
echo "View logs:    docker-compose -f docker-compose.airgap.yml logs -f"
echo ""
EOFDEPLOY

chmod +x "${PACKAGE_DIR}/deploy.sh"

# Create tarball
echo ""
echo "Creating deployment package..."
tar -czf "${PACKAGE_NAME}.tar.gz" "${PACKAGE_DIR}"

# Calculate size and checksum
SIZE=$(du -h "${PACKAGE_NAME}.tar.gz" | cut -f1)
CHECKSUM=$(sha256sum "${PACKAGE_NAME}.tar.gz" | cut -d' ' -f1)

echo ""
echo "========================================="
echo "Package created successfully!"
echo "========================================="
echo ""
echo "Package: ${PACKAGE_NAME}.tar.gz"
echo "Size:    ${SIZE}"
echo "SHA256:  ${CHECKSUM}"
echo ""
echo "To deploy in air-gapped environment:"
echo "  1. Transfer ${PACKAGE_NAME}.tar.gz to target server"
echo "  2. tar -xzf ${PACKAGE_NAME}.tar.gz"
echo "  3. cd ${PACKAGE_NAME}"
echo "  4. ./deploy.sh"
echo ""
