"""
Entity Type Classifier: 인제스트 시점 엔티티 타입 분류 패스 (B안, opt-in)

noun_extractor/contextual_grouper는 recall 보존을 위해 타입을 "Entity"로
고정한다. 본 모듈은 정규화가 끝난 entity_dictionary(canonical name 목록)를
입력받아, 별도 LLM 패스로 각 엔티티에 일반 클래스 라벨(Person/Organization/
Location/... 또는 도메인 특화 클래스)을 배정한다.

opt-in 플래그(enable_entity_typing)가 True일 때만 파이프라인에서 호출된다.
비활성 시에는 이 모듈이 아예 임포트/실행되지 않으므로 기존 동작에 영향 없음.

design: docs/design-ingest-entity-typing-b.md §3.2
"""
import json
import logging
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

# 배치당 상한 엔티티 수. 배치가 여러 개면 로그로 남기고, 무음 절단은 하지 않는다
# (모든 엔티티가 결국 어느 배치에서든 분류되며, 실패 시 "Entity" 폴백으로 채워짐).
BATCH_SIZE = 80


class EntityTypeClassifier:
    """정규화된 엔티티 사전을 받아 canonical name -> class label 매핑을 생성한다."""

    def __init__(self, llm=None, llm_config: Optional[Dict[str, Any]] = None):
        cfg = llm_config or {}
        client_kwargs: Dict[str, Any] = {"api_key": cfg.get("api_key") or settings.OPENAI_API_KEY}
        if cfg.get("base_url"):
            client_kwargs["base_url"] = cfg["base_url"]
        if cfg.get("extra_headers"):
            client_kwargs["default_headers"] = cfg["extra_headers"]
        self.client = AsyncOpenAI(**client_kwargs)
        self.model = cfg.get("model", "gpt-4o")
        self.system_prompt = (
            "당신은 지식 그래프의 엔티티에 클래스(타입)를 배정하는 전문가입니다.\n"
            "각 엔티티에 대해 가장 적합한 '일반 클래스'를 하나씩 배정하세요.\n\n"
            "[권장 클래스 예시] (참고용, 강제 목록 아님)\n"
            "Person, Organization, Location, Date, Event, Work, Concept\n\n"
            "[원칙]\n"
            "1. 위 예시에 없더라도 도메인에 더 적합한 클래스가 있으면 그것을 사용해도 됩니다.\n"
            "2. **일관성이 최우선**입니다: 의미상 같은 부류의 엔티티는 항상 동일한 클래스 라벨을 사용하세요. "
            "새로운 라벨을 남발하지 마세요(예: 'Actor'와 'Performer'를 섞어 쓰지 말고 하나로 통일).\n"
            "3. 클래스 라벨은 짧은 영문 단어/구(PascalCase 권장)로 작성하세요.\n"
            "4. 판단이 애매하거나 확신이 없으면 반드시 'Entity'로 배정하세요 (누락 없이 전량 분류).\n"
            "5. 입력된 모든 엔티티에 대해 빠짐없이 응답해야 합니다.\n\n"
            "반드시 아래 JSON 배열 형식으로만 응답하세요. 다른 설명 텍스트는 포함하지 마세요.\n"
            '[{"name": "엔티티명", "type": "클래스"}, ...]'
        )

    async def classify(
        self,
        entity_dictionary: Dict[str, Dict[str, Any]],
        domain_hint: str = "",
    ) -> Dict[str, str]:
        """entity_dictionary의 canonical name들에 대해 {name: type} 매핑을 반환한다.

        모든 이름은 응답에 포함되도록 시도하며, 배치 실패나 응답 누락 시
        해당 이름은 안전 폴백으로 'Entity'가 채워진다.
        """
        names = list(entity_dictionary.keys())
        if not names:
            return {}

        batches: List[List[str]] = [
            names[i : i + BATCH_SIZE] for i in range(0, len(names), BATCH_SIZE)
        ]

        if len(batches) > 1:
            logger.info(
                f"[EntityTypeClassifier] Classifying {len(names)} entities in {len(batches)} batches "
                f"(batch_size={BATCH_SIZE})..."
            )
        else:
            logger.info(f"[EntityTypeClassifier] Classifying {len(names)} entities in a single batch...")

        result: Dict[str, str] = {}
        for batch_idx, batch in enumerate(batches):
            try:
                batch_result = await self._classify_batch(batch, domain_hint)
            except Exception as e:
                logger.error(f"[EntityTypeClassifier] Batch {batch_idx + 1}/{len(batches)} failed: {e}")
                batch_result = {}
            result.update(batch_result)

        # 응답에서 누락된 이름은 안전 폴백
        missing = 0
        for name in names:
            if name not in result:
                result[name] = "Entity"
                missing += 1
        if missing:
            logger.warning(f"[EntityTypeClassifier] {missing} entities missing from LLM response(s); defaulted to 'Entity'.")

        non_entity = sum(1 for v in result.values() if v != "Entity")
        logger.info(f"[EntityTypeClassifier] Done. {non_entity}/{len(names)} entities assigned a non-generic type.")

        return result

    async def _classify_batch(self, batch: List[str], domain_hint: str) -> Dict[str, str]:
        entities_str = "\n".join(f"- {name}" for name in batch)
        domain_part = f"\n[문서 도메인 힌트]\n{domain_hint}\n" if domain_hint else ""

        user_prompt = (
            f"{domain_part}\n"
            "다음 엔티티 목록 각각에 클래스를 배정하세요.\n\n"
            f"[엔티티 목록]\n{entities_str}\n\n"
            "JSON 배열로만 응답하세요."
        )

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
        content = response.choices[0].message.content or ""
        parsed = self._parse_json_response(content)

        batch_result: Dict[str, str] = {}
        if isinstance(parsed, list):
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                type_label = str(item.get("type", "")).strip()
                if not name:
                    continue
                batch_result[name] = type_label if type_label else "Entity"
        else:
            logger.warning(
                f"[EntityTypeClassifier] Could not parse a JSON array from LLM response: {content[:200]}..."
            )

        return batch_result

    def _parse_json_response(self, text: str) -> Optional[Any]:
        """LLM 응답에서 ```json 코드펜스를 제거하고 JSON을 파싱한다."""
        cleaned = text.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in cleaned:
            parts = cleaned.split("```")
            if len(parts) >= 2:
                cleaned = parts[1]

        try:
            return json.loads(cleaned.strip())
        except json.JSONDecodeError as e:
            logger.error(f"[EntityTypeClassifier] JSON parse failed: {e}")
            return None
