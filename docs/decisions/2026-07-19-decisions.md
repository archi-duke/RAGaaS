# 2026-07-19 ~ 20 의사결정 로그

> 11/17 복원 — `design/schema/design-ontology-schema-extraction-v2.md`, `design/schema/design-ingest-entity-typing-b.md`, `design/schema/design-structured-json-yaml-ontology.md`, PR #38 (07-19), PR #39 (07-20) 에서 옮겼다.

## D1. A안 — 승격 스키마 추출에 그래프 프로파일 주입 (PR #38)

- 평평한 로컬네임 리스트 → 관계별 빈도·예시 트리플·개념 빈도·타입 힌트. domain/range 는 관찰된 패턴만.
- **기각**: 인제스트 타입 복원(재인제스트 필요 → B안으로 분리). 4-클래스 고정 few-shot 의 앵커링 해제.
- 실측(dry-run): 클래스 6 → 7, instance_types 0 → 143 (A+B: 9, 200).
- **이후**: 11/14~15 승격 재설계·시드 스키마로 대체.

## D2. B안 — 인제스트 시점 엔티티 타입 부여, opt-in (PR #38)

- 높은 recall 명사 추출 뒤 별도 LLM 패스(`EntityTypeClassifier`)로 타입. 가이드형 개방 어휘. Fuseki `rdf:type`, Neo4j 동적 라벨. `enable_entity_typing` 기본 False.
- **기각**: 추출 프롬프트에서 타입 복원(recall 저하), 폐쇄형 어휘(도메인 다양성), 완전 개방형(파편화), 소급 백필.
- Entity 폴백 53% → 11%.

## D3. C안 — JSON/YAML 을 결정론적으로 온톨로지 매핑 (PR #39, Phase 1+2)

- 객체=노드, 스칼라=데이터 속성, id 참조=객체 속성, 배열=다중 엣지, type/컨테이너 키=클래스. 레코드는 문장 청크로. 구조화 문서는 auto-inverse 억제.
- Phase 2: 승격 KB 만 기존 TBox 와 정렬, 불일치 시 기존 preview/confirm 흐름에서 사람 검토. **매핑 규칙은 저장하지 않음** (→ 11/14 KB 매핑 규칙으로 사실상 번복).
- **기각**: B안 classifier(구조가 타입을 줌), 별도 검토 단계.

## D4. C안 Phase 3 (JSON Schema → TBox) · 문서 간 엔티티 동일성

- JSON Schema 를 감지하면 클래스·속성·domain/range 를 결정적으로 TBox 에 반영 (`graph2ontology/json_schema_converter.py`), 스키마가 없으면 인스턴스로 유도 → A안 승격으로 확정. SHACL 은 후속.
- 문서 간 같은 엔티티 해소 (`ingest_service/app/core/entity_resolver.py`).
- PR #39 에 함께 squash 머지됨 (head 65e1e93) — main 에 있다. (11/17 '미반영' 으로 잘못 기록했다가 정정)
