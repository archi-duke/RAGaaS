"""
Entity Normalizer Module

그래프 추출 후, 적재 직전에 엔티티 이름을 Canonical Form으로 정규화합니다.
유사한 엔티티를 통합하는 기능을 포함합니다.
"""
import re
import numpy as np
from typing import List, Dict, Any, Optional


class EntityNormalizer:
    """엔티티 정규화 클래스"""
    
    def normalize_triples(self, triples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        트리플 리스트의 subject/object를 정규화합니다.
        
        Args:
            triples: 원본 트리플 리스트
            
        Returns:
            정규화된 트리플 리스트
        """
        for t in triples:
            t["subject"] = self._to_canonical(t.get("subject", ""))
            t["object"] = self._to_canonical(t.get("object", ""))
            # predicate도 정리 (공백 등)
            t["predicate"] = self._normalize_predicate(t.get("predicate", ""))
        
        return triples
    
    def _to_canonical(self, name: str) -> str:
        """
        엔티티 이름을 Canonical Form으로 변환합니다.
        
        Args:
            name: 원본 엔티티 이름
            
        Returns:
            정규화된 엔티티 이름
        """
        if not name:
            return name
        
        # 1. 앞뒤 공백 제거
        name = name.strip()
        
        # 2. 따옴표/괄호 제거
        name = name.strip('"\'')
        
        # 3. 앞 번호 제거: "4. 성기훈" → "성기훈"
        name = re.sub(r'^\d+[\.\\)\\]]\s*', '', name)
        name = re.sub(r'^\([a-zA-Z0-9]\)\s*', '', name)
        
        # 4. 특수문자 정리 (언더스코어 유지)
        # 예: "성기훈_456" 같은 것은 유지
        
        # 5. 연속 공백 → 단일 공백
        name = ' '.join(name.split())
        
        # 6. 앞뒤 공백 재정리
        return name.strip()
    
    def _normalize_predicate(self, predicate: str) -> str:
        """
        관계 이름을 정규화합니다.
        
        Args:
            predicate: 원본 관계 이름
            
        Returns:
            정규화된 관계 이름
        """
        if not predicate:
            return predicate
        
        # 공백 정리
        predicate = predicate.strip()
        predicate = ' '.join(predicate.split())
        
        return predicate
    
    def resolve_duplicates(self, triples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        중복 트리플을 제거합니다.
        (동일한 subject-predicate-object 조합)
        
        Args:
            triples: 트리플 리스트
            
        Returns:
            중복 제거된 트리플 리스트
        """
        seen = set()
        unique_triples = []
        
        for t in triples:
            key = (t.get("subject"), t.get("predicate"), t.get("object"))
            if key not in seen:
                seen.add(key)
                unique_triples.append(t)
        
        return unique_triples
    
    # ============================================================
    # Entity Normalization - Similarity-based Merging
    # ============================================================
    
    async def calculate_similarity_embedding(
        self,
        text1: str,
        text2: str,
        embed_model
    ) -> float:
        """임베딩 기반 유사도 계산 (코사인 유사도)"""
        try:
            embedding1 = await embed_model.aget_text_embedding(text1)
            embedding2 = await embed_model.aget_text_embedding(text2)
            
            # 코사인 유사도 계산
            similarity = np.dot(embedding1, embedding2) / (
                np.linalg.norm(embedding1) * np.linalg.norm(embedding2)
            )
            return float(similarity)
        except Exception as e:
            print(f"[EntityNormalizer] Embedding similarity error: {e}")
            return 0.0
    
    def calculate_similarity_string(
        self,
        text1: str,
        text2: str
    ) -> float:
        """문자열 기반 유사도 계산 (Jaro-Winkler)"""
        try:
            from rapidfuzz import fuzz
            # Jaro-Winkler 유사도 (0-100) -> 0-1로 정규화
            return fuzz.ratio(text1.lower(), text2.lower()) / 100.0
        except ImportError:
            # rapidfuzz가 없으면 간단한 문자열 매칭
            if text1.lower() == text2.lower():
                return 1.0
            elif text1.lower() in text2.lower() or text2.lower() in text1.lower():
                return 0.8
            else:
                return 0.0
    
    async def calculate_similarity_llm(
        self,
        text1: str,
        text2: str,
        llm
    ) -> float:
        """LLM 기반 유사도 판단"""
        try:
            prompt = f"""Are these two entities referring to the same thing?
Entity 1: {text1}
Entity 2: {text2}

Answer with a similarity score from 0.0 to 1.0, where:
- 1.0 = definitely the same entity
- 0.5 = possibly related
- 0.0 = completely different

Respond with ONLY the numeric score."""
            
            response = await llm.acomplete(prompt)
            score = float(response.text.strip())
            return max(0.0, min(1.0, score))  # Clamp to [0, 1]
        except Exception as e:
            print(f"[EntityNormalizer] LLM similarity error: {e}")
            return 0.0
    
    async def find_similar_entities(
        self, 
        triples: List[Dict[str, Any]], 
        algorithm: str = "embedding",
        threshold: float = 0.85,
        embed_model = None,
        llm = None
    ) -> Dict[str, List[str]]:
        """
        트리플에서 유사한 엔티티를 찾아 그룹화합니다. (최적화 버전)
        """
        # 1. 모든 고유 엔티티 추출
        entities = set()
        for t in triples:
            subject = t.get("subject", "")
            obj = t.get("object", "")
            if subject and subject.strip():
                entities.add(subject.strip())
            if obj and obj.strip():
                entities.add(obj.strip())
        
        entities = sorted(list(entities))  # 일관성을 위해 정렬
        n = len(entities)
        
        if n == 0:
            return {}
        
        print(f"[EntityNormalizer] Finding similar entities among {n} unique entities using {algorithm} algorithm (optimized)...")
        
        similarity_matrix = np.zeros((n, n))
        
        if algorithm == "embedding" and embed_model:
            # [OPTIMIZATION] 모든 임베딩을 한 번에 가져오기
            print(f"[EntityNormalizer] Pre-calculating {n} embeddings...")
            embeddings = []
            for entity in entities:
                embeddings.append(await embed_model.aget_text_embedding(entity))
            
            emb_array = np.array(embeddings)
            
            # [OPTIMIZATION] 행렬 연산으로 코사인 유사도 일괄 계산
            print(f"[EntityNormalizer] Calculating similarity matrix via matrix multiplication...")
            norm = np.linalg.norm(emb_array, axis=1, keepdims=True)
            normalized_emb = emb_array / norm
            similarity_matrix = np.dot(normalized_emb, normalized_emb.T)
            
        elif algorithm == "string":
            from rapidfuzz import fuzz
            for i in range(n):
                for j in range(i + 1, n):
                    sim = fuzz.ratio(entities[i].lower(), entities[j].lower()) / 100.0
                    similarity_matrix[i, j] = sim
                    similarity_matrix[j, i] = sim # 대칭 행렬 유지
        else:
            # LLM 등 다른 방식은 기존처럼 루프 (필요 시 추후 최적화)
            for i in range(n):
                for j in range(i + 1, n):
                    if algorithm == "llm" and llm:
                        sim = await self.calculate_similarity_llm(entities[i], entities[j], llm)
                        similarity_matrix[i, j] = sim
                        similarity_matrix[j, i] = sim
        
        # 2. 그룹화 (Union-Find 알고리즘 사용)
        parent = list(range(n)) # 각 엔티티의 부모 인덱스
        
        def find(i):
            if parent[i] == i:
                return i
            parent[i] = find(parent[i])
            return parent[i]
        
        def union(i, j):
            root_i = find(i)
            root_j = find(j)
            if root_i != root_j:
                parent[root_j] = root_i
                return True
            return False

        # 유사도 임계값을 넘는 엔티티 쌍을 병합
        merged_pairs_count = 0
        for i in range(n):
            for j in range(i + 1, n): # 상삼각 행렬만 확인
                if similarity_matrix[i, j] >= threshold:
                    print(f"[EntityNormalizer] Merging candidate: '{entities[i]}' <-> '{entities[j]}' (score: {similarity_matrix[i, j]:.4f})")
                    if union(i, j):
                        merged_pairs_count += 1
        
        print(f"[EntityNormalizer] Processed {merged_pairs_count} potential merges above threshold.")

        # 최종 그룹 생성
        # key: root entity index, value: list of entity indices in the group
        grouped_indices = {}
        for i in range(n):
            root = find(i)
            if root not in grouped_indices:
                grouped_indices[root] = []
            grouped_indices[root].append(i)
        
        final_groups = {} # key: canonical entity, value: list of variants
        for root_idx, indices_in_group in grouped_indices.items():
            if len(indices_in_group) > 1: # 2개 이상의 엔티티가 묶인 그룹만 처리
                group_entities = [entities[i] for i in indices_in_group]
                
                # Canonical form: 가장 긴 엔티티 선택 (또는 다른 기준)
                canonical = max(group_entities, key=len)
                variants = [e for e in group_entities if e != canonical]
                
                final_groups[canonical] = variants
                print(f"[EntityNormalizer] Group formed: Canonical='{canonical}', Variants={variants}")
        
        print(f"[EntityNormalizer] Found {len(final_groups)} entity groups to merge")
        return final_groups
    
    async def generate_normalization_suggestions(
        self,
        triples: List[Dict[str, Any]],
        algorithm: str = "embedding",
        threshold: float = 0.85,
        embed_model = None,
        llm = None
    ) -> List[Dict[str, Any]]:
        """
        통합 제안 목록을 생성합니다.
        
        Returns:
            [
                {
                    "group_id": 0,
                    "canonical": "성기훈",
                    "variants": ["기훈", "Gihun", "Sung-GiHun"],
                    "count": 15  # 이 엔티티가 등장하는 트리플 수
                },
                ...
            ]
        """
        groups = await self.find_similar_entities(
            triples, algorithm, threshold, embed_model, llm
        )
        
        suggestions = []
        for group_id, (canonical, variants) in enumerate(groups.items()):
            # 이 엔티티가 등장하는 트리플 수 계산
            all_forms = [canonical] + variants
            count = sum(
                1 for t in triples 
                if t.get("subject") in all_forms or t.get("object") in all_forms
            )
            
            suggestions.append({
                "group_id": group_id,
                "canonical": canonical,
                "variants": variants,
                "count": count,
            })
        
        return suggestions
    
    def apply_selected_normalizations(
        self,
        triples: List[Dict[str, Any]],
        suggestions: List[Dict[str, Any]],
        selected_group_ids: List[int]
    ) -> List[Dict[str, Any]]:
        """선택된 그룹만 통합을 적용합니다."""
        # 매핑 테이블 생성
        mapping = {}
        for suggestion in suggestions:
            if suggestion["group_id"] in selected_group_ids:
                canonical = suggestion["canonical"]
                for variant in suggestion["variants"]:
                    mapping[variant] = canonical
        
        # 트리플에 매핑 적용
        normalized_triples = []
        for t in triples:
            normalized_triple = t.copy()
            subject = t.get("subject", "")
            obj = t.get("object", "")
            
            normalized_triple["subject"] = mapping.get(subject, subject)
            normalized_triple["object"] = mapping.get(obj, obj)
            
            normalized_triples.append(normalized_triple)
        
        return normalized_triples
    
    def apply_all_normalizations(
        self,
        triples: List[Dict[str, Any]],
        suggestions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """모든 제안된 통합을 자동으로 적용합니다."""
        all_group_ids = [s["group_id"] for s in suggestions]
        return self.apply_selected_normalizations(triples, suggestions, all_group_ids)


# Singleton instance
entity_normalizer = EntityNormalizer()
