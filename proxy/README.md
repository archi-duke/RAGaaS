# Samsung DS API Gateway Proxy

Samsung DS API 게이트웨이를 **OpenAI 호환 API 포맷**으로 중계하는 경량 FastAPI 프록시 서비스입니다.

## 📋 지원 엔드포인트

| 엔드포인트 | 메서드 | 업스트림 대상 |
|---|---|---|
| `/v1/embeddings` | POST | `https://apigw.samsungds.net:8443/embedding/1/v1/embeddings` |
| `/v1/chat/completions` | POST | `http://apigw.samsungds.net:8000/gpt-oss/1/gpt-oss-120b/v1/chat/completions` |
| `/health` | GET | 상태 확인 |

## ⚙️ 환경변수 설정

프로젝트 루트의 `.env` 파일에 아래 값을 채워주세요.

```bash
# 임베딩 API 인증 티켓 (x-dep-ticket 헤더)
EMBEDDING_DEP_TICKET=credential:TICKET-...

# LLM API 인증 티켓 (X-Dep-Ticket 헤더) — 보통 임베딩과 동일
LLM_DEP_TICKET=credential:TICKET-...

# LLM API 호출자 AD ID
LLM_USER_ID=your.adid
```

## 🚀 로컬 실행

```bash
# proxy/ 폴더 이내에서
chmod +x run.sh
./run.sh
```

또는 직접:
```bash
cd proxy
pip install -r requirements.txt
uvicorn app.main:app --port 8010 --reload
```

## 🐳 Docker 실행

`docker-compose.yml`에서 `samsung-ds-proxy` 서비스 주석을 해제 후:
```bash
docker compose up samsung-ds-proxy
```

## 🔧 RAGaaS 연결 방법

백엔드/인제스트 서비스에서 아래 설정값으로 프록시를 OpenAI 호환 엔드포인트로 사용합니다.

- **Base URL**: `http://localhost:8010`
- **API Key**: 임의 값(예: `dummy-key`) — 프록시에서 무시됨
- **Embedding Model**: `text-embedding-ada-002` (프록시가 Samsung DS로 중계)
- **LLM Model**: `openai/gpt-oss-120b` (프록시가 Samsung DS로 중계)

## 구조

```
proxy/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI 앱 진입점
│   ├── config.py        # 환경변수 설정
│   └── routers/
│       ├── __init__.py
│       ├── embedding.py # /v1/embeddings 라우터
│       └── chat.py      # /v1/chat/completions 라우터
├── requirements.txt
├── Dockerfile
├── run.sh               # 로컬 실행 스크립트
└── README.md
```
