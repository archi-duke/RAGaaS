
import os
import json
import requests
from typing import Optional, Dict

class SPARQLGenerator:
    """자연어 질문을 SPARQL 쿼리로 변환하는 LLM 기반 생성기"""

    SYSTEM_PROMPT = """당신은 SPARQL 및 지식 그래프(Knowledge Graph) 전문가입니다.
주어진 Ontology 스키마와 규칙을 기반으로, 자연어 질문을 실행 가능한 SPARQL 1.1 쿼리로 변환하세요.

[Ontology Schema]
1. Namespaces (Prefixes):
   - rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
   - rdfs: <http://www.w3.org/2000/01/rdf-schema#>
   - owl: <http://www.w3.org/2002/07/owl#>
   - xsd: <http://www.w3.org/2001/XMLSchema#>
   - inst: <http://example.org/onto/inst/>  (인스턴스)
   - rel: <http://example.org/onto/rel/>    (관계/Predicate)
   - prop: <http://example.org/onto/prop/>  (속성/Property)

2. 주요 구조:
   - 모든 엔티티는 URI를 가집니다 (예: inst:성기훈).
   - 엔티티의 이름(Label)은 `rdfs:label` 속성에 저장됩니다 (문자열 리터럴, @ko 언어 태그 권장).
   - 예: `?s rdfs:label "성기훈"@ko`

3. 관계 (Relationships):
   - 관계(Predicate)는 주로 `rel:` 네임스페이스를 사용합니다.
   - 예: `?s rel:스승 ?o`, `?s rel:사용 ?o`
   - 관계 방향이 모호할 경우, 양방향 혹은 Property Path(`|` 또는 `^`)를 고려하세요.

[작성 원칙]
1. **PREFIX 필수 포함**: 쿼리 시작 부분에 위 Namespaces를 모두 정의하세요.
2. **엔티티 매칭**: 이름으로 찾을 때는 `rdfs:label`을 사용하세요. 정확한 이름이 아닐 경우 `CONTAINS`나 `REGEX`를 사용할 수 있지만 가능하면 정확한 매칭을 선호하세요.
3. **관계 탐색**:
   - 질문의 의도를 파악하여 적절한 `rel:관계명`을 추론하세요.
   - **Inverse Relation (역방향 관계)**: '스승'을 찾으라는 질문은 '제자' 관계의 역방향일 수도 있습니다.
   - Property Path 사용 권장: `(rel:스승|^rel:제자)` 와 같이 작성하면 방향 무관하게 탐색 가능합니다.
4. **결과 반환**:
   - 가능한 `DISTINCT`를 사용하세요.
   - 찾고자 하는 대상의 URI와 Label을 함께 반환하거나, 명확한 변수명을 사용하세요.

[예시]
질문: "성기훈의 스승은 누구야?"
SPARQL:
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rel: <http://example.org/onto/rel/>
SELECT DISTINCT ?teacherLabel WHERE {
  ?s rdfs:label "성기훈"@ko .
  ?s (rel:스승|^rel:제자) ?teacher .
  ?teacher rdfs:label ?teacherLabel .
}

반드시 JSON 형식으로 응답하세요:
{
  "thought": "논리적 추론 과정",
  "sparql": "생성된 SPARQL 쿼리"
}
"""

    def __init__(
        self,
        llm_endpoint: Optional[str] = None,
        llm_model: str = "gpt-4o",
        api_key: Optional[str] = None,
    ):
        self.llm_endpoint = llm_endpoint or "https://api.openai.com/v1/chat/completions"
        self.llm_model = llm_model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    def generate(self, question: str, context: Optional[str] = None, mode: str = "ontology", inverse_relation: str = "auto", custom_prompt: Optional[str] = None, schema_info: Optional[Dict] = None) -> Dict:
        """자연어 질문을 SPARQL로 변환 (custom_prompt, schema_info 지원)"""
        
        system_prompt = self.SYSTEM_PROMPT

        # [NEW] Schema Injection
        if schema_info:
            classes_part = schema_info.get("classes", {})
            c_list = list(classes_part.keys()) if isinstance(classes_part, dict) else classes_part
            p_list = schema_info.get("properties", [])
            
            # Format nicely
            c_str = "\n".join([f"- {c.split('/')[-1].split('#')[-1]} (<{c}>)" for c in sorted(c_list)[:100]])
            p_str = "\n".join([f"- {p.split('/')[-1].split('#')[-1]} (<{p}>)" for p in sorted(p_list)[:100]])
            
            system_prompt += f"\n\n[DEFINED ONTOLOGY SCHEMA]\nRefer to these Classes and Properties when generating SPARQL:\n\n**Classes**:\n{c_str}\n\n**Properties**:\n{p_str}\n"

        # Add instruction for inverse relation
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
