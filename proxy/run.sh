#!/usr/bin/env bash
# ------------------------------------------------------
# Samsung DS API Gateway 프록시 로컬 실행 스크립트
# ------------------------------------------------------
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# .env 로드
if [ -f "../.env" ]; then
    export $(grep -v '^#' ../.env | xargs)
fi

# 가상환경 생성 및 패키지 설치
if [ ! -d "venv" ]; then
    echo "📦 가상환경 생성 중..."
    python3 -m venv venv
fi

source venv/bin/activate
pip install -q -r requirements.txt

echo "🚀 Samsung DS API Proxy 시작 (포트: 8010)"
uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload
