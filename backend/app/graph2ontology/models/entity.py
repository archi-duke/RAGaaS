"""엔티티 레지스트리 모델"""

from typing import Union, Optional,  Optional, Union
from pydantic import BaseModel, Field


class EntityEntry(BaseModel):
    """엔티티 레지스트리 항목"""
    canonical_uri: str = Field(..., description="정규 IRI")
    canonical_label: str = Field(..., description="정규 라벨 (한국어)")
    labels: list[str] = Field(default_factory=list, description="모든 라벨 (altLabel 포함)")
    same_as: list[str] = Field(default_factory=list, description="owl:sameAs로 연결된 URI 목록")
    entity_type: str = Field(..., description="엔티티 유형 (class/property/relation/instance)")
    first_seen_run_id: str = Field(..., description="최초 등록 실행 ID")
    last_seen_run_id: str = Field(..., description="마지막 확인 실행 ID")
    
    def add_alias(self, alias: str) -> None:
        """별칭 추가"""
        if alias not in self.labels:
            self.labels.append(alias)
    
    def merge_with(self, old_uri: str) -> None:
        """다른 엔티티와 병합 (owl:sameAs)"""
        if old_uri not in self.same_as:
            self.same_as.append(old_uri)


class EntityRegistry(BaseModel):
    """엔티티 레지스트리"""
    entries: dict[str, EntityEntry] = Field(
        default_factory=dict, 
        description="URI -> EntityEntry 매핑"
    )
    label_to_uri: dict[str, str] = Field(
        default_factory=dict,
        description="라벨 -> canonical URI 역인덱스"
    )
    
    def register(
        self,
        uri: str,
        label: str,
        entity_type: str,
        run_id: str,
        aliases: Optional[list[str]] = None
    ) -> EntityEntry:
        """새 엔티티 등록 또는 기존 엔티티 업데이트"""
        if uri in self.entries:
            # 기존 엔티티 업데이트
            entry = self.entries[uri]
            entry.last_seen_run_id = run_id
            if label not in entry.labels:
                entry.labels.append(label)
            if aliases:
                for alias in aliases:
                    entry.add_alias(alias)
        else:
            # 새 엔티티 생성
            all_labels = [label]
            if aliases:
                all_labels.extend(aliases)
            
            entry = EntityEntry(
                canonical_uri=uri,
                canonical_label=label,
                labels=all_labels,
                entity_type=entity_type,
                first_seen_run_id=run_id,
                last_seen_run_id=run_id,
            )
            self.entries[uri] = entry
        
        # 역인덱스 업데이트
        for lbl in entry.labels:
            self.label_to_uri[lbl] = uri
        
        return entry
    
    def lookup_by_label(self, label: str) -> Optional[str]:
        """라벨로 canonical URI 조회"""
        return self.label_to_uri.get(label)
    
    def get_entry(self, uri: str) -> Optional[EntityEntry]:
        """URI로 엔티티 조회"""
        return self.entries.get(uri)
    
    def merge_entities(self, canonical_uri: str, old_uri: str) -> None:
        """두 엔티티 병합 (old -> canonical)"""
        if canonical_uri not in self.entries:
            return
        if old_uri not in self.entries:
            return
        
        canonical = self.entries[canonical_uri]
        old = self.entries[old_uri]
        
        # 라벨 병합
        for label in old.labels:
            canonical.add_alias(label)
            self.label_to_uri[label] = canonical_uri
        
        # sameAs 추가
        canonical.merge_with(old_uri)
        
        # 이전 엔티티의 sameAs도 병합
        for same_uri in old.same_as:
            if same_uri not in canonical.same_as:
                canonical.same_as.append(same_uri)
        
        # 이전 엔티티 제거 (별도로 유지하고 싶으면 남겨둘 수 있음)
        # del self.entries[old_uri]
    
    @property
    def total_entities(self) -> int:
        return len(self.entries)
