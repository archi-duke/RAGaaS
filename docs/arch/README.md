# arch/ — 초기 아키텍처 설계 산출물 (설계 이력 🏛️)

> **주의**: 이 디렉토리는 2026-02 설계 단계의 산출물이다. ASR→QS→후보구조(CA)→결정으로 이어지는
> 추적 체계는 유지 가치가 있으나, **다음 내용은 현행 구현과 다르다**:
>
> | 문서 기술 | 현행 | 정정 기록 |
> |---|---|---|
> | 메타데이터 DB = SQLite | MongoDB + Beanie | [ADR-003](../adr/ADR-003-mongodb-metadata-store.md) |
> | 메시지 브로커 + Ingestion Worker (CA-203) | HTTP 마이크로서비스 + 콜백 | [ADR-002](../adr/ADR-002-http-ingest-service.md) |
> | CA-102 파이프라인 기각 | 스테이지 파이프라인 **채택됨** | [ADR-001](../adr/ADR-001-pipeline-based-retrieval.md) |
> | 헥사고날 폴더 구조 (`app/domain/ports` 등) | 미채택 — 실구조는 [`../architecture/코드_구조_분석.md`](../architecture/코드_구조_분석.md) | — |
>
> **현행 사양은 [`../specification-v2.md`](../specification-v2.md) 를 볼 것.**

## 디렉토리 역할

| 경로 | 역할 |
|---|---|
| `usecase/UC-*.md` | **유스케이스 요구사항 명세 정본** — 액터·사전/사후조건·기본/대안/예외 시나리오 |
| `system/UC-*.md` | usecase 에서 **파생된 기술 설계** — Boundary/Control/Entity 시퀀스 다이어그램 (같은 파일명이지만 중복이 아님) |
| `system/model.md` | 시스템 컨텍스트 모델 (UC 전체 개요) |
| `business.md`, `System.md`, `functional.md`, `usecases.md` | 비즈니스/시스템/기능 요구사항 |
| `asr.md`, `qualities.md`, `quality/` | ASR·품질 속성·품질 시나리오(QS) |
| `candidate/`, `decision/`, `evaluation/` | 후보 구조(CA)·평가·결정 |
| `architecture.md`, `architecture/` | 통합 명세 및 스타일/모듈/배치 상세 |
