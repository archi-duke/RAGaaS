import json
import logging
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

class DictionaryBuilder:
    def __init__(self, llm_model_config: Optional[Dict[str, Any]] = None):
        cfg = llm_model_config or {}
        self.cfg = cfg
        self.model = cfg.get("model")

    async def extract_entity_candidates(self, texts: List[str], sampling_size: int = 30000) -> List[str]:
        """
        문서 전체 또는 샘플 텍스트에서 모든 엔티티와 주요 개념을 추출합니다. (1차 패스)
        """
        full_text = "\n\n".join(texts)
        
        # 샘플링
        if sampling_size > 0 and len(full_text) > sampling_size:
            sample_text = full_text[:sampling_size]
        else:
            sample_text = full_text
        
        prompt = """
        아래 텍스트를 분석하여 모든 고유 명사(인물, 조직, 장소, 사건 등)와 중요한 핵심 개념(기술, 도구, 규칙 등)을 추출하세요.
        지식 그래프 구축을 위한 엔티티 목록을 만드는 것이 목적입니다.
        
        [지시 사항]
        1. 가능한 한 많은 엔티티를 추출하세요.
        2. 텍스트에 나타난 그대로의 명칭을 사용하세요. (예: "성기훈", "기훈", "456번" 모두 개별 추출)
        3. 인물뿐만 아니라 장소, 물건, 중요한 개념도 빠짐없이 포함하세요.
        
        [출력 형식 (JSON)]
        {{
            "entities": ["성기훈", "기훈", "오일남", "오징어 게임", "장풍", "깐부"]
        }}
        
        텍스트:
        {text}
        """

        try:
            logger.info(f"[Pass 1] Extracting candidates from sample ({len(sample_text)} chars)...")
            from app.core.llm import achat
            data = json.loads(await achat(
                self.cfg,
                [{"role": "user", "content": prompt.format(text=sample_text)}],
                model=self.model, temperature=0, response_format={"type": "json_object"},
            ))
            candidates = data.get("entities", [])
            unique_candidates = sorted(list(set([c.strip() for c in candidates if c.strip()])))
            logger.info(f"[Pass 1] Successfully extracted {len(unique_candidates)} candidates.")
            return unique_candidates
        except Exception as e:
            logger.error(f"Error in extract_entity_candidates: {e}")
            return []

    async def build_global_dictionary(self, candidates: List[str]) -> Dict[str, str]:
        """
        추출된 후보들을 기반으로 유의어 및 변이형을 정규화된 이름으로 매핑합니다. (2차 패스)
        """
        if not candidates:
            return {}

        prompt = """
        아래는 문서에서 추출된 엔티티 목록입니다. 같은 대상(인물, 사물, 개념)을 가리키는 이름들을 그룹화하고 대표 이름(Canonical Name)을 정하세요.
        
        [규칙]
        1. 가장 공식적이거나 완전한 이름을 대표 이름으로 정하세요. (예: "기훈" -> "성기훈")
        2. 확실하게 같은 대상을 지칭하는 경우에만 그룹화하세요.
        
        [출력 형식 (JSON)]
        {{
            "mappings": {{
                "기훈": "성기훈",
                "456번": "성기훈",
                "상우": "조상우"
            }}
        }}
        
        후보 목록:
        {candidates}
        """
        
        candidates_str = ", ".join(candidates)
        
        try:
            logger.info(f"[Pass 2] Consolidating {len(candidates)} candidates...")
            from app.core.llm import achat
            data = json.loads(await achat(
                self.cfg,
                [{"role": "user", "content": prompt.format(candidates=candidates_str)}],
                model=self.model, temperature=0, response_format={"type": "json_object"},
            ))
            mappings = data.get("mappings", {})
            
            # 모든 후보에 대해 자기 자신으로의 매핑 보장
            for c in candidates:
                if c not in mappings:
                    mappings[c] = c
            
            logger.info(f"[Pass 2] Global dictionary built with {len(mappings)} mappings.")
            return mappings
        except Exception as e:
            logger.error(f"Error in build_global_dictionary: {e}")
            return {c: c for c in candidates}

dictionary_builder = DictionaryBuilder()
