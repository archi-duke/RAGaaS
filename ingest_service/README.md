# Ingest Service

LlamaIndex 기반 문서 인제스션 서비스

## 구조
- `app/main.py`: FastAPI 진입점
- `app/core/pipeline.py`: LlamaIndex 파이프라인
- `app/workers/ingest_worker.py`: RQ 워커
- `app/api/ingest.py`: API 라우터
