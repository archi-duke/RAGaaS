# QS-006-벡터-그래프-DB-간-삭제-정합성

## 개요

### Quality Scenario ID
QS-006

### 제목
벡터-그래프 DB 간 삭제 정합성

### 설명
사용자가 특정 지식 베이스 또는 문서를 삭제했을 때, 연동된 여러 저장소(Vector DB, Graph DB, Metadata DB) 간의 데이터가 누락 없이 동시에 완전히 삭제되는 무결성을 측정합니다.

### 품질 속성
데이터 정합성 (Consistency)

## 환경

### 시스템 상태
- 정상 운영 중 소거 작업 수행 (Cleanup Operation)
- 다중 저장소(Heterogeneous Storage) 시스템 환경

### 초기 조건
- 대상 지식 베이스에 수만 건의 벡터 청크와 수천 건의 지식 트리플이 저장되어 있는 상태
- 각 DB 간의 참조 ID(Document ID, KB ID)가 정상적으로 매핑되어 있음

### 관련 컴포넌트
- KBManager (Control)
- VectorStore (Entity)
- GraphStore (Entity)
- MetadataDB (Entity)

## 동작
1. 시스템 관리자가 지식 베이스 삭제(Delete KB) 명령을 호출한다.
2. KBManager가 각 저장소 엔진에 개별 삭제 명령을 전파한다.
3. 벡터 컬렉션, 그래프 파티션, 메타데이터 레코드 및 원본 파일이 순차적 또는 병렬로 삭제된다.
4. 삭제 완료 후 모든 저장소 엔진에서 '성공' 응답을 수신한다.

## 측정
- **측정 항목**: 삭제 무결성 및 고립 데이터(Dangling data) 존재 여부
- **측정 공식**:
```
Integrity_Error_Rate = (삭제 후 잔존 데이터 건수 / 삭제 전 전체 데이터 건수) * 100
```
- **측정 방법**:
  - 삭제 프로세스 완료 후, 각 DB 엔진의 Low-level API를 사용하여 삭제된 ID로 조회를 수행하여 검색 결과가 0건인지 검증
  - 삭제 작업 중 특정 DB 장애 시 롤백 또는 수동 정리 안내 로직 동작 여부 확인

## 관련 문서

- UC-003-지식 베이스 삭제
- KBManager
- QS-007-검색-파라미터-반영-즉시성 (데이터 상태 동기화 측면)
