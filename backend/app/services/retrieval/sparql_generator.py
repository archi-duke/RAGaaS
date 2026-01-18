import os
import json
import requests
from typing import Optional, Dict

class SPARQLGenerator:
    """자연어 질문을 SPARQL 쿼리로 변환하는 LLM 기반 생성기"""

    DEFAULT_SYSTEM_PROMPT = """당신은 SPARQL 및 지식 그래프(Knowledge Graph) 전문가입니다.
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
   - 엔티티의 이름(Label)은 `rdfs:label` 속성에 저장됩니다. (문자열 리터럴)
   - 예: `?s rdfs:label "성기훈"`
   - **관계 방향성 중요**: 
     - `rel:제자` (is student of): `[학생] rel:제자 [스승]` -> 학생이 주어(Subject), 스승이 목적어(Object)
     - `rel:스승` (is teacher of): `[스승] rel:스승 [학생]` -> 스승이 주어(Subject), 학생이 목적어(Object)
   - **스승을 찾을 때**: `?student rel:제자 ?teacher` 또는 `?teacher rel:스승 ?student` 를 탐색하세요.

3. 관계 탐색:
   - 질문의 의도를 파악하여 적절한 `rel:관계명`을 추론하세요.
   - 방향 무관 탐색이 필요할 경우 Property Path(`|` 또는 `^`)를 사용하세요. 
     - 예: 스승을 찾기 위해 `(rel:제자|^rel:스승)` 사용 가능.

[작성 원칙]
1. **PREFIX 필수 포함**: 쿼리 시작 부분에 위 Namespaces를 모두 정의하세요.
2. **엔티티 매칭 (중요)**: 
   - 이름으로 찾을 때는 `rdfs:label`을 사용하되, `FILTER(STR(?label) = "이름")` 형식을 권장합니다.
3. **결과 반환**:
   - 가능한 `DISTINCT`를 사용하세요.

[예시]
질문: "성기훈의 스승은 누구야?"
SPARQL:
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rel: <http://rag.local/rel/>
SELECT DISTINCT ?teacherLabel WHERE {
  ?s rdfs:label ?sLabel .
  FILTER(STR(?sLabel) = "성기훈") .
  ?s (rel:제자|^rel:스승) ?teacher .
  ?teacher rdfs:label ?teacherLabel .
}

반드시 JSON 형식으로 응답하세요:
{
  "thought": "논리적 추론 과정",
  "sparql": "생성된 SPARQL 쿼리"
}
"""
    
    SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT # For UI compat


    def __init__(
        self,
        llm_endpoint: Optional[str] = None,
        llm_model: str = "gpt-4o",
        api_key: Optional[str] = None,
    ):
        self.llm_endpoint = llm_endpoint or "https://api.openai.com/v1/chat/completions"
        self.llm_model = llm_model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    def generate(self, question: str, context: Optional[str] = None, mode: str = "ontology", inverse_relation: str = "auto", custom_prompt: Optional[str] = None, schema_info: Optional[Dict] = None, system_prompt_override: Optional[str] = None) -> Dict:
        """자연어 질문을 SPARQL로 변환 (custom_prompt 지원)"""
        
        # Dynamic Load from File (Priority: Override > File > Default)
        from pathlib import Path
        
        system_prompt = ""
        
        if system_prompt_override:
            system_prompt = system_prompt_override
        else:
            # Select prompt file based on mode/schema availability
            if schema_info:
                prompt_path = Path("data/prompts/sparql_ontology_prompt.txt")
            else:
                prompt_path = Path("data/prompts/sparql_generation_prompt.txt")
    
            if prompt_path.exists():
                system_prompt = prompt_path.read_text(encoding="utf-8")
            else:
                system_prompt = self.DEFAULT_SYSTEM_PROMPT

        
        # Inject Schema Info if available (Promoted Ontology)
        if schema_info:
            # Construct a readable schema description
            schema_text = "\n\n[Active Ontology Schema]\n"
            schema_text += "This Knowledge Base follows a specific ontology. Use these Classes and Relations PREFERENTIALLY:\n"
            
            classes = schema_info.get('classes', {})
            if classes:
                schema_text += "\n1. Classes:\n"
                for cls_key, cls_val in classes.items():
                    # Support both dict (metadata) and simple formats
                    if isinstance(cls_val, dict):
                        label = cls_val.get('label', cls_key)
                        desc = cls_val.get('description', '')
                        schema_text += f"   - {label}" + (f": {desc}" if desc else "") + "\n"
                    else:
                        schema_text += f"   - {cls_key}\n"

            relations = schema_info.get('relations', [])
            if relations:
                schema_text += "\n2. Relations:\n"
                for rel in relations:
                    if isinstance(rel, dict):
                        label = rel.get('label', rel.get('uri', 'Unknown'))
                        schema_text += f"   - {label}\n"
                    elif isinstance(rel, str):
                        schema_text += f"   - {rel}\n"
            
            system_prompt += schema_text

        if inverse_relation == "auto" or inverse_relation == "always":
            system_prompt += "\n[추가 지침]\n- 관계 탐색 시 Property Path `|` 와 역방향 `^` 연산자를 적극 활용하여 방향성 문제를 해결하세요 (예: `rel:스승|^rel:제자`)."

        # Add Custom Prompt (User Override)
        if custom_prompt:
            system_prompt += f"\n\n[USER CUSTOM INSTRUCTIONS (PRIORITY OVERRIDE)]\n{custom_prompt}\n"

        user_content = f"사용자 질문: {question}"
        if context:
            user_content += f"\n\n[컨텍스트]\n{context}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.0,
        }

        try:
            response = requests.post(
                self.llm_endpoint,
                headers=headers,
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            
            content = response.json()["choices"][0]["message"]["content"]
            
            # Extract JSON
            content = content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            return json.loads(content.strip())

        except Exception as e:
            print(f"[SPARQLGenerator] Error: {e}")
            return {"error": str(e), "sparql": None}
