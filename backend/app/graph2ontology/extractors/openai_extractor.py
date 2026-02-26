"""OpenAI 기반 LLM 추출기"""

import json
import os
from pathlib import Path
from typing import Union, Optional,  Optional, Union

# .env 파일 로드
from dotenv import load_dotenv
load_dotenv()

from app.graph2ontology.extractors.base import BaseExtractor
from app.graph2ontology.models.candidate import (
    CandidateExtractionResult,
    ClassCandidate,
    PropertyCandidate,
    RelationCandidate,
    InstanceCandidate,
    Triple,
)
from app.graph2ontology.models.chunk import OEChunk


EXTRACTION_PROMPT = """당신은 텍스트에서 지식 그래프(Knowledge Graph)를 구축하기 위해 엔티티와 관계를 추출하는 전문가 AI입니다.

주어진 텍스트를 분석하여 다음 요소들을 정확하게 추출하세요:

1. **Entities (개체)**:
   - 텍스트에서 중요한 의미를 가지는 명사구 (예: 인물, 조직, 장소, 사건, 개념, 물건, 작품 등).
   - 가능한 한 구체적인 고유명사나 전문 용어를 식별하세요.
   - 각 엔티티의 유형(Type)을 추론하여 명시하세요 (예: Person, Organization, Location, Event, Concept 등).

2. **Relations (관계)**:
   - 두 엔티티 사이의 의미 있는 연결 고리.
   - 문맥상 명확하게 드러난 관계를 동사형이나 관계형 명사로 표현하세요 (예: ~의 부분이다, ~를 포함한다, ~와 관련있다, ~를 수행하다 등).
   - 주어(Subject)와 목적어(Object)가 바뀔 경우 의미가 달라지는지 주의하세요.
   - **복합 관계 추출**: '~이자 ~이다', '~이고 ~하다' 등 접속사로 연결된 문장에서 여러 관계를 모두 놓치지 말고 추출하세요. (예: "A는 B의 제자이며 C의 스승이다" → (A, 제자, B), (A, 스승, C))
   - **주어 생략 추론**: 문장에서 주어가 생략된 경우, 바로 앞 문장의 주어나 문맥상 가장 적절한 엔티티를 주어로 추론하여 연결하세요. (예: "그는 장풍의 고수이다. 또한 Duke의 제자이다." → (그, 제자, Duke))

3. **Attributes (속성)**:
   - 엔티티의 성질, 상태, 수치, 날짜 등 구체적인 값.
   - (Entity, Attribute_Name, Value) 형태로 추출하세요.

반드시 아래 JSON 형식으로만 응답하세요:
```json
{{
  "entities": [
    {{"name": "엔티티명", "type": "추론된_타입", "description": "문맥상 의미 요약"}}
  ],
  "triples": [
    {{"subject": "주어_엔티티", "predicate": "관계_서술어", "object": "목적어_엔티티", "confidence": 0.9}}
  ],
  "properties": [
    {{"entity": "엔티티명", "property": "속성명", "value": "속성값"}}
  ]
}}
```

**추출 원칙:**
- **사실 기반**: 텍스트에 명시되거나 강력하게 암시된 내용만 추출하세요. 추측을 지양하세요.
- **핵심 중심**: 문장의 핵심 정보를 담고 있는 관계를 우선적으로 추출하세요. 단순한 수식어나 부가적인 정보는 제외해도 좋습니다.
- **명확성**: 모호한 대명사(그, 그녀, 이것)는 가능한 한 가리키는 대상(원래 엔티티)으로 치환하여 추출하세요.
- **언어**: 결과값(엔티티명, 관계명 등)은 텍스트의 언어(한국어)를 따르되, 필요한 경우 영문을 병기하거나 표준 용어를 사용할 수 있습니다.
- **Confidence**: 추출한 정보의 확실성을 0.5 ~ 1.0 사이의 실수로 표현하세요.

텍스트:
{text}
"""


class OpenAIExtractor(BaseExtractor):
    """OpenAI API 기반 추출기"""
    
    def __init__(
        self,
        confidence_threshold: float = 0.5,
        llm_endpoint: Optional[str] = None,
        llm_model: str = "gpt-4o-mini",
        api_key: Optional[str] = None,
        examples_path: Optional[str] = None,
    ):
        super().__init__(confidence_threshold)
        self.llm_endpoint = llm_endpoint or "https://api.openai.com/v1/chat/completions"
        self.llm_model = llm_model
        from app.core.config import settings as app_settings
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "") or app_settings.OPENAI_API_KEY
        self.examples_prompt = ""

        if not self.api_key:
            raise ValueError("API Key가 설정되지 않았습니다. Provider 설정을 확인하거나 OPENAI_API_KEY 환경변수를 설정하세요.")
            
        # Few-shot 예제 로드
        if examples_path and Path(examples_path).exists():
            try:
                import yaml
                import json
                with open(examples_path, "r", encoding="utf-8") as f:
                    examples = yaml.safe_load(f)
                    if examples:
                        self.examples_prompt = "\n\n[참고 예제]\n"
                        for ex in examples:
                            # 예제 포맷팅
                            ex_text = ex.get("text", "")
                            ex_triples = ex.get("triples", [])
                            # JSON 형태로 변환하여 보여줌
                            ex_json = json.dumps({"triples": ex_triples}, ensure_ascii=False)
                            self.examples_prompt += f"텍스트: {ex_text}\n결과: {ex_json}\n\n"
            except Exception as e:
                print(f"Warning: 예제 파일 로드 실패 - {e}")
    
    def extract(
        self,
        chunk: OEChunk,
        run_id: str,
    ) -> CandidateExtractionResult:
        """청크에서 LLM을 사용하여 트리플 추출"""
        text = chunk.text
        if not text.strip():
            return CandidateExtractionResult(doc_id=chunk.doc_id, run_id=run_id) # Changed from ExtractionResult to CandidateExtractionResult
            
        prompt = EXTRACTION_PROMPT.format(text=text[:3000])
        
        # 예제가 있으면 프롬프트에 추가
        if self.examples_prompt:
             # 마지막 "텍스트:" 앞에 예제 삽입
             prompt = prompt.replace("텍스트:\n", f"{self.examples_prompt}텍스트:\n")
        
        result = CandidateExtractionResult(
            doc_id=chunk.doc_id,
            doc_ver=chunk.doc_ver,
            run_id=run_id,
        )
        
        # LLM 호출
        llm_result = self.call_llm(prompt) # Changed to pass the formatted prompt
        
        if not llm_result:
            return result
        
        # 엔티티 → 클래스/인스턴스로 변환
        # 수정: 기본적으로 Instance로 취급하고, 명확한 추상 개념만 Class로 분류
        # 이는 고유명사(인물 등)가 불필요하게 Class로 정의되는 문제를 방지함
        ABSTRACT_TYPES = ["Concept", "Class", "Category", "Type", "Abstraction", "Role", "Idea"]
        
        for entity in llm_result.get("entities", []):
            name = entity.get("name", "").strip()
            # 빈 이름 필터링 (중요)
            if not name:
                continue
                
            entity_type = entity.get("type", "Concept")
            
            # 타입이 추상 개념 리스트에 있거나, 이름 자체가 추상적일 경우 Class로 매핑
            # 더 안전한 접근: 대부분의 추출된 엔티티는 인스턴스(개체)일 확률이 높음
            is_abstract = any(t.lower() in entity_type.lower() for t in ABSTRACT_TYPES)
            
            if is_abstract:
                result.classes.append(ClassCandidate(
                    label=name,
                    description=entity.get("description", ""),
                    confidence=0.8,
                    source_text=entity.get("description", ""),
                    source_chunk_id=chunk.chunk_id,
                ))
            else:
                result.instances.append(InstanceCandidate(
                    label=name,
                    class_label=entity_type, # LLM이 추출한 타입을 클래스 타입으로 사용 (예: "Person", "Character")
                    confidence=0.8,
                    source_text=entity.get("description", ""),
                    source_chunk_id=chunk.chunk_id,
                ))
        
        # 트리플 변환
        for triple in llm_result.get("triples", []):
            s = triple.get("subject", "").strip()
            p = triple.get("predicate", "").strip()
            o = triple.get("object", "").strip()
            
            # 빈 요소가 있는 트리플 필터링
            if not s or not p or not o:
                continue

            result.triples.append(Triple(
                subject=s,
                predicate=p,
                object=o,
                confidence=triple.get("confidence", 0.7),
                source_text=f"{s} {p} {o}",
                source_chunk_id=chunk.chunk_id,
            ))
            
            # 관계도 추가
            result.relations.append(RelationCandidate(
                label=p,
                domain_class=s,
                range_class=o,
                confidence=triple.get("confidence", 0.7),
                source_text=f"{s} {p} {o}",
                source_chunk_id=chunk.chunk_id,
            ))
        
        # 속성 변환
        for prop in llm_result.get("properties", []):
            e_name = prop.get("entity", "").strip()
            p_name = prop.get("property", "").strip()
            p_val = prop.get("value", "")
            
            if not e_name or not p_name:
                continue

            if isinstance(p_val, list):
                p_val = ", ".join(map(str, p_val))
            
            result.properties.append(PropertyCandidate(
                label=p_name,
                domain_class=e_name,
                confidence=0.8,
                source_text=f"{e_name}의 {p_name}는 {p_val}",
                source_chunk_id=chunk.chunk_id,
            ))
            
            # 속성을 Triple 형태로 변환
            result.triples.append(Triple(
                subject=e_name,
                predicate=p_name,
                object=str(p_val),
                object_is_literal=True,
                confidence=0.9,  # 속성은 높은 신뢰도 부여
                source_text=f"{e_name}의 {p_name}는 {p_val}",
                source_chunk_id=chunk.chunk_id,
            ))
        
        return result
    
    def call_llm(self, prompt_text: str) -> dict:
        """OpenAI API 호출
        
        Args:
            prompt_text: 완성된 프롬프트 문자열 (extract 메소드에서 구성됨)
        """
        import requests
        
        # prompt = EXTRACTION_PROMPT.format(text=text[:3000])  # 제거됨 (외부에서 처리)
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": "You are a knowledge graph extraction expert. Always respond in valid JSON only."},
                {"role": "user", "content": prompt_text}
            ],
            "temperature": 0.1,
            "max_tokens": 2000,
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
            
            # JSON 파싱 (```json ... ``` 형식 처리)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            return json.loads(content.strip())
            
        except requests.RequestException as e:
            print(f"LLM API 호출 실패: {e}")
            return {}
        except json.JSONDecodeError as e:
            print(f"JSON 파싱 실패: {e}")
            return {}
