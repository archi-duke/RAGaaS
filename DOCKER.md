# Docker Deployment Guide

## Prerequisites

- Docker Engine 20.10+
- Docker Compose 2.0+
- At least 4GB of RAM available
- OpenAI API key

## Quick Start

### 1. Setup Environment Variables

```bash
# Copy example env file
cp .env.example .env

# Edit .env and add your OpenAI API key
nano .env
```

### 2. Build and Start All Services

```bash
# Build and start in detached mode
docker-compose up -d --build

# View logs
docker-compose logs -f
```

### 3. Access the Application

- **Frontend**: http://localhost
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Milvus**: localhost:19530
- **MinIO Console**: http://localhost:9001

## Services

| Service | Container Name | Port | Description |
|---------|---------------|------|-------------|
| Frontend | ragaas-frontend | 80 | React SPA (Nginx) |
| Backend | ragaas-backend | 8000 | FastAPI Server |
| Milvus | milvus-standalone | 19530 | Vector Database |
| etcd | milvus-etcd | 2379 | Milvus Metadata |
| MinIO | milvus-minio | 9000 | Milvus Storage |

## Common Commands

```bash
# Start services
docker-compose up -d

# Stop services
docker-compose down

# View logs
docker-compose logs -f [service_name]

# Rebuild after code changes
docker-compose up -d --build

# Remove all data (including volumes)
docker-compose down -v

# Restart a specific service
docker-compose restart backend
```

## Data Persistence

Data is stored in the following locations:

- **SQLite DB**: `./backend/data/rag_system.db`
- **Milvus Data**: `./volumes/milvus/`
- **MinIO Data**: `./volumes/minio/`
- **etcd Data**: `./volumes/etcd/`

## Troubleshooting

### Backend can't connect to Milvus

```bash
# Check Milvus logs
docker-compose logs standalone

# Restart Milvus
docker-compose restart standalone
```

### Frontend shows API errors

```bash
# Check backend logs
docker-compose logs backend

# Verify backend is running
curl http://localhost:8000/docs
```

### Out of memory errors

```bash
# Check resource usage
docker stats

# Increase Docker memory limit in Docker Desktop settings
```

## Development vs Production

### Development (Current Setup)

- SQLite database
- Local file storage
- Single server deployment

### Production Recommendations

1. **Database**: Switch to PostgreSQL
2. **File Storage**: Use S3 or cloud storage
3. **Scaling**: Use Kubernetes for orchestration
4. **Security**: 
   - Enable HTTPS
   - Use secrets management
   - Implement authentication
5. **Monitoring**: Add Prometheus + Grafana

## Updating the Application

```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose down
docker-compose up -d --build
```

## Cleanup

```bash
# Stop and remove containers, networks
docker-compose down

# Also remove volumes (deletes all data!)
docker-compose down -v

# Remove built images
docker rmi ragaas-backend ragaas-frontend
```
