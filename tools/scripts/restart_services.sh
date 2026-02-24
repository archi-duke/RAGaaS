#!/bin/bash

# RAGaaS Service Restart Script (Local Hosting)

PROJECT_ROOT="/Users/dukekimm/Works/RAGaaS"
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"

echo "🛑 Stopping existing services..."
lsof -ti:5173,8000,8001 | xargs kill -9 2>/dev/null || true
pkill -f "uvicorn" || true
pkill -f "vite" || true
sleep 2

echo "🚀 Starting Backend (8000)..."
cd "$PROJECT_ROOT/backend"
source venv/bin/activate
nohup uvicorn main:app --host 0.0.0.0 --port 8000 --reload > "$LOG_DIR/backend.log" 2>&1 &
echo $! > "$LOG_DIR/backend.pid"

echo "🚀 Starting Ingest Service (8001)..."
cd "$PROJECT_ROOT/ingest_service"
source venv/bin/activate
nohup uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload > "$LOG_DIR/ingest.log" 2>&1 &
echo $! > "$LOG_DIR/ingest.pid"

echo "🚀 Starting Frontend (5173)..."
cd "$PROJECT_ROOT/frontend"
# Use --host 0.0.0.0 to ensure it's accessible
nohup npm run dev -- --host 0.0.0.0 > "$LOG_DIR/frontend.log" 2>&1 &
echo $! > "$LOG_DIR/frontend.pid"

echo "⏳ Waiting for services to warm up..."
sleep 5

echo "📊 Service Status:"
lsof -i :5173 -i :8000 -i :8001

echo "✅ All services initiated. Check logs in $LOG_DIR"
