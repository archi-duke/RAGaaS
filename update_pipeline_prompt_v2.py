
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = "mongodb://root:example@localhost:27017"
DB_NAME = "ragaas"
KB_ID = "d2980afe-3238-4d34-854d-400bb3937bb9"

# [핵심 수정] SELECT 절에 ?s ?p ?o가 포함되도록 유도하는 프롬프트
CORRECT_PROMPT = """당신은 SPARQL 및 지식 그래프(Knowledge Graph) 전문가입니다.
주어진 Ontology 스키마와 규칙을 기반으로, 자연어 질문을 실행 가능한 SPARQL 1.1 쿼리로 변환하세요.

[Ontology Schema]
1. Namespaces (Prefixes):
   - rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
   - rdfs: <http://www.w3.org/2000/01/rdf-schema#>
   - owl: <http://www.w3.org/2002/07/owl#>
   - xsd: <http://www.w3.org/2001/XMLSchema#>
   - inst: <http://rag.local/inst/>  (인스턴스)
   - rel: <http://rag.local/rel/>    (관계/Predicate)
   - prop: <http://rag.local/prop/>  (속성/Property)
   - class: <http://rag.local/class/> (클래스)

2. 주요 구조 및 규칙:
   - 모든 엔티티는 URI를 가집니다 (예: inst:성기훈).
   - 엔티티의 이름(Label)은 `rdfs:label` 속성에 저장됩니다 (문자열 리터럴).
   - 예: `?s rdfs:label "성기훈"`
   - **관계 방향성 중요**: 
     - `rel:제자` (is student of): `[학생] rel:제자 [스승]` -> 학생이 주어(Subject), 스승이 목적어(Object)
     - `rel:스승` (is teacher of): `[스승] rel:스승 [학생]` -> 스승이 주어(Subject), 학생이 목적어(Object)
   - **스승을 찾을 때**: `?student rel:제자 ?teacher` 또는 `?teacher rel:스승 ?student` 를 탐색하세요.

3. 관계 탐색:
   - Property Path(`|` 또는 `^`)를 사용하여 유연하게 탐색하세요. 
     - 예: 스승을 찾기 위해 `(rel:제자|^rel:스승)` 사용 가능.

[작성 원칙 - 중요]
1. **트리플 반환 필수**: 
   - 정답만 찾지 말고, **정답을 찾기 위해 거쳐간 경로의 트리플(?s ?p ?o)도 함께 반환**해야 합니다.
   - 단, Property Path를 사용할 경우 경로를 분해하기 어려우므로, **최종 정답 엔티티와 그 엔티티를 가리키는 직전 트리플**을 반환하도록 하세요.
   - 가장 확실한 방법은 **정답 엔티티의 URI(?uri)와 레이블(?label)**을 반환하는 것입니다. 백엔드에서 추가 정보를 조회할 것입니다.
2. **PREFIX 필수 포함**: 쿼리 시작 부분에 위 Namespaces를 모두 정의하세요.
3. **엔티티 매칭**: `FILTER(STR(?label) = "이름")` 사용.

[예시]
질문: "성기훈의 스승의 스승은 누구야?"
SPARQL:
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rel: <http://rag.local/rel/>
SELECT DISTINCT ?grandTeacher ?grandTeacherLabel WHERE {
  ?s rdfs:label ?sLabel .
  FILTER(STR(?sLabel) = "성기훈") .
  ?s (rel:제자|^rel:스승) ?teacher .
  ?teacher (rel:제자|^rel:스승) ?grandTeacher .
  ?grandTeacher rdfs:label ?grandTeacherLabel .
}

반드시 JSON 형식으로 응답하세요:
{
  "thought": "논리적 추론 과정",
  "sparql": "생성된 SPARQL 쿼리"
}
"""

async def update_pipeline_config():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    collection = db["knowledge_bases"]
    
    # Check current pipeline
    kb = await collection.find_one({"_id": KB_ID})
    if not kb:
        print("KB not found")
        return

    pipeline = kb.get("pipeline_config", {})
    stages = pipeline.get("stages", [])
    
    updated_stages = []
    
    for stage in stages:
        if stage.get("type") == "graph":
            print("Found Graph stage. Injecting prompt into params...")
            params = stage.get("params", {})
            params["sparql_prompt_template"] = CORRECT_PROMPT
            stage["params"] = params
        updated_stages.append(stage)
    
    pipeline["stages"] = updated_stages
    
    # Update DB
    result = await collection.update_one(
        {"_id": KB_ID},
        {"$set": {"pipeline_config": pipeline}}
    )
    
    print(f"Matched: {result.matched_count}, Modified: {result.modified_count}")

if __name__ == "__main__":
    asyncio.run(update_pipeline_config())
