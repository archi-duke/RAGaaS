"""엔티티 레지스트리 빌더"""

import json
from pathlib import Path
from typing import Union, Optional,  Optional, Union

from app.graph2ontology.models.entity import EntityRegistry, EntityEntry
from app.graph2ontology.models.candidate import CandidateExtractionResult


class EntityRegistryBuilder:
    """엔티티 레지스트리 관리 및 빌드"""
    
    def __init__(
        self,
        base_uri: str = "http://example.org/onto/",
    ):
        """
        Args:
            base_uri: 온톨로지 베이스 URI
        """
        self.base_uri = base_uri
        self.registry = EntityRegistry()
    
    def _to_uri(self, label: str, entity_type: str) -> str:
        """라벨을 URI로 변환"""
        prefix_map = {
            "class": "class/",
            "property": "prop/",
            "relation": "rel/",
            "instance": "inst/",
        }
        prefix = prefix_map.get(entity_type, "entity/")
        safe_label = "".join(
            c if c.isalnum() else "_" for c in label
        ).strip("_")
        return f"{self.base_uri}{prefix}{safe_label}"
    
    def register_from_candidates(
        self,
        result: CandidateExtractionResult,
    ) -> int:
        """추출 결과에서 엔티티 등록
        
        Returns:
            등록된 엔티티 수
        """
        count = 0
        
        # 클래스 등록
        for cls in result.classes:
            uri = self._to_uri(cls.label, "class")
            self.registry.register(
                uri=uri,
                label=cls.label,
                entity_type="class",
                run_id=result.run_id,
            )
            count += 1
        
        # 속성 등록
        for prop in result.properties:
            uri = self._to_uri(prop.label, "property")
            self.registry.register(
                uri=uri,
                label=prop.label,
                entity_type="property",
                run_id=result.run_id,
            )
            count += 1
        
        # 관계 등록
        for rel in result.relations:
            uri = self._to_uri(rel.label, "relation")
            self.registry.register(
                uri=uri,
                label=rel.label,
                entity_type="relation",
                run_id=result.run_id,
            )
            count += 1
        
        # 인스턴스 등록
        for inst in result.instances:
            uri = self._to_uri(inst.label, "instance")
            self.registry.register(
                uri=uri,
                label=inst.label,
                entity_type="instance",
                run_id=result.run_id,
            )
            count += 1
        
        # 트리플에서 엔티티 추출
        for triple in result.triples:
            # Subject
            subj_uri = self._to_uri(triple.subject, "instance")
            self.registry.register(
                uri=subj_uri,
                label=triple.subject,
                entity_type="instance",
                run_id=result.run_id,
            )
            count += 1
            
            # Object (리터럴이 아닌 경우)
            if not triple.object_is_literal:
                obj_uri = self._to_uri(triple.object, "instance")
                self.registry.register(
                    uri=obj_uri,
                    label=triple.object,
                    entity_type="instance",
                    run_id=result.run_id,
                )
                count += 1
        
        return count
    
    def add_alias(self, canonical_label: str, alias: str) -> bool:
        """별칭 추가
        
        Returns:
            성공 여부
        """
        uri = self.registry.lookup_by_label(canonical_label)
        if uri:
            entry = self.registry.get_entry(uri)
            if entry:
                entry.add_alias(alias)
                self.registry.label_to_uri[alias] = uri
                return True
        return False
    
    def merge(self, canonical_label: str, old_label: str) -> bool:
        """엔티티 병합 (old -> canonical)
        
        Returns:
            성공 여부
        """
        canonical_uri = self.registry.lookup_by_label(canonical_label)
        old_uri = self.registry.lookup_by_label(old_label)
        
        if canonical_uri and old_uri:
            self.registry.merge_entities(canonical_uri, old_uri)
            return True
        return False
    
    def serialize(self, output_path: Union[str, Path]) -> None:
        """레지스트리를 JSON으로 저장"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "base_uri": self.base_uri,
            "total_entities": self.registry.total_entities,
            "entries": {
                uri: entry.model_dump()
                for uri, entry in self.registry.entries.items()
            }
        }
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def load(cls, input_path: Union[str, Path]) -> "EntityRegistryBuilder":
        """JSON에서 레지스트리 로드"""
        input_path = Path(input_path)
        
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        builder = cls(base_uri=data.get("base_uri", "http://example.org/onto/"))
        
        for uri, entry_data in data.get("entries", {}).items():
            entry = EntityEntry(**entry_data)
            builder.registry.entries[uri] = entry
            for label in entry.labels:
                builder.registry.label_to_uri[label] = uri
        
        return builder

    def load_synonyms_yaml(self, yaml_path: Union[str, Path]) -> int:
        """YAML 파일에서 동의어 사전 로드
        
        Format:
          - label: "Canonical Name"
            type: "instance"
            aliases: ["alias1", "alias2"]
        """
        import yaml
        
        path = Path(yaml_path)
        if not path.exists():
            return 0
            
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
            
        count = 0
        for item in data:
            label = item.get("label")
            if not label:
                continue
                
            entity_type = item.get("type", "instance")
            aliases = item.get("aliases", [])
            
            # URI 생성 (이미 있으면 조회)
            uri = self.registry.lookup_by_label(label)
            if not uri:
                uri = self._to_uri(label, entity_type)
            
            # 등록/업데이트
            self.registry.register(
                uri=uri,
                label=label,
                entity_type=entity_type,
                run_id="manual-yaml",
                aliases=aliases
            )
            count += 1
            
        return count
