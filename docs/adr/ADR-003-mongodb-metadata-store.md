# ADR-003: 메타데이터 저장소 SQLite → MongoDB(Beanie) 전환

- **상태**: Accepted (2026-07-15 기록)
- **관련**: `docs/_archive/specification-v1.md` §2.1 및 `docs/arch/architecture.md` 컨텍스트 다이어그램의 SQLite 결정을 **대체**함

## 맥락

초기 사양 문서(`docs/_archive/specification-v1.md` §2.1)는 메타데이터 DB로 **SQLite**를 지정했다. "간편함을 위해 선택, 추후 PostgreSQL로 확장 가능"이라는 사유가 명시되어 있었고, `docs/arch/architecture.md`의 컨텍스트 다이어그램에도 `SQLite[(Metadata DB)]` 노드로 반영되어 있었다.

그러나 실제 구현은 **MongoDB + Beanie ODM**(Motor 기반 async)으로 이루어졌다. `backend/app/models/`에 `knowledge_base.py`, `document.py`, `provider.py`, `prompt.py` 등 Beanie `Document` 서브클래스가 정의되어 있고, 각 모델의 `Settings.name`으로 컬렉션(`knowledge_bases`, `documents`, `custom_providers`, `builtin_provider_configs`, `prompts`)이 매핑된다. 이외에도 `triple_chunk_mappings` 관련 로직이 `backend/app/api/knowledge_base.py`, `backend/app/api/document.py`, `backend/app/services/ingestion/cleanup_service.py`, `backend/migrate_triple_mapping.py`에 존재하며, `backend/scripts/migrate_sqlite_to_mongo.py`가 남아 있어 SQLite에서 MongoDB로 실제 마이그레이션이 수행되었음을 뒷받침한다.

*(추정)* 전환 동기는 KB(지식베이스)의 `pipeline_config`·모델 설정 등 **중첩 dict 스키마가 잦게 진화**하는 특성상 스키마리스 문서 DB가 유리했고, FastAPI의 async 모델과 Motor/Beanie의 결합이 자연스러우며, GoJIRA 스택과의 shared-infra 통합(단일 MongoDB 인스턴스 공유)이 유리했을 것으로 보인다. 이 근거는 코드/설정에서 직접 확인되지 않은 추정이다.

## 결정

메타데이터 저장소를 SQLite에서 **MongoDB(Beanie ODM, Motor 비동기 드라이버)**로 전환한다.

- 컬렉션: `knowledge_bases`, `documents`, `custom_providers`, `builtin_provider_configs`, `prompts`, `triple_chunk_mappings`.
- 버전 핀: `backend/requirements.txt`에 `beanie<2`, `motor<4`를 고정. beanie 2.x는 Motor를 지원하지 않아 기동 크래시가 발생하므로(`docs/PLATFORM-INTEGRATION.md` §4.6), 미고정 설치 사고를 막기 위한 명시적 핀이다.
- 자체 컨테이너로 MongoDB를 운영하지 않고, **shared-infra의 외부 MongoDB**를 참조한다. `backend/app/core/config.py`의 `MONGO_URI`(기본값 `mongodb://root:example@mongo:27017`), `MONGO_DB`(기본값 `ragaas`) 설정과 `deploy/docker-compose.yml`의 `MONGO_URI=${MONGO_URI:?required}` 환경변수 요구로 확인된다. 인증은 `authSource=admin` 기반.
- 연결/초기화는 `backend/app/core/database.py`에서 `AsyncIOMotorClient` + `init_beanie`로 수행.

## 결과

**긍정적 영향**

- KB `pipeline_config` 등 중첩 dict 스키마 변경 시 마이그레이션 스크립트 없이 유연하게 대응 가능.
- FastAPI async 엔드포인트와 Motor/Beanie 비동기 호출이 자연스럽게 결합되어 블로킹 DB 호출이 없다.
- shared-infra의 단일 MongoDB 인스턴스를 GoJIRA 스택과 공유함으로써 인프라 관리 부담이 줄었다.

**부정적 영향 / 부채**

- MongoDB는 다중 컬렉션/다중 저장소(MongoDB·Milvus·Fuseki/그래프 DB) 간 트랜잭션을 기본 지원하지 않는다. `backend/app/services/ingestion/cleanup_service.py`의 `CleanupService.perform_cascading_deletion`이 Graph → Vector → MongoDB 순서로 캐스케이딩 삭제를 수행하며, 중간 실패 시 MongoDB 문서를 `ERROR` 상태로 남겨 정합성을 애플리케이션 레벨에서 수동 처리한다("Enforces transactional integrity" 주석 참조). 즉 DB 자체의 트랜잭션 보장이 아니라 코드 레벨 보상 로직에 의존한다.
- `beanie<2`, `motor<4` 버전 핀을 계속 관리해야 하는 부담이 생겼다. beanie 상위 버전으로 업그레이드하려면 Motor 의존성 전체를 재검토해야 한다.
- `docs/_archive/specification-v1.md`, `docs/arch/architecture.md`가 SQLite 기준으로 방치되어 실제 구현과 불일치한 상태였다(본 ADR 작성 시점 기준). 본 ADR이 이 불일치를 문서상으로 정정하는 역할을 겸한다.
- `backend/scripts/migrate_sqlite_to_mongo.py`, `backend/migrate_triple_mapping.py` 등 1회성 마이그레이션 스크립트가 저장소에 잔존해 있어 정리 대상이다.

## 참조 파일

- `docs/_archive/specification-v1.md` (§2.1, 12행 — SQLite 원 결정), 418행
- `docs/arch/architecture.md` (컨텍스트 다이어그램, 20행 `SQLite[(Metadata DB)]`, 29행)
- `backend/app/models/knowledge_base.py`, `document.py`, `provider.py`, `prompt.py` (Beanie `Document` 모델 및 `Settings.name` 컬렉션 매핑)
- `backend/requirements.txt` (`beanie<2`, `motor<4` 핀)
- `backend/app/core/config.py` (`MONGO_URI`, `MONGO_DB`)
- `backend/app/core/database.py` (`AsyncIOMotorClient` + `init_beanie` 초기화)
- `deploy/docker-compose.yml` (`MONGO_URI` 필수 환경변수, shared-infra 참조)
- `backend/app/services/ingestion/cleanup_service.py` (`CleanupService.perform_cascading_deletion` — 애플리케이션 레벨 정합성 보장)
- `backend/scripts/migrate_sqlite_to_mongo.py` (SQLite → MongoDB 마이그레이션 이력)
- `docs/PLATFORM-INTEGRATION.md` (§4.6 beanie/motor 핀 사유)
