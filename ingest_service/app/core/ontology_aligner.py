"""
Ontology Aligner (C안 Phase 2)

이미 온톨로지 승격된 KB(`is_promoted`)에 구조화 문서가 들어올 때, 추출된
후보 클래스/속성을 **기존 TBox와 대조**하여 matched / similar / new / disjoint로
분류한다. 이 결과(alignment proposal)가 불일치 검토 UI의 데이터 소스가 된다.

design: docs/design-structured-json-yaml-ontology.md §6 (온톨로지 인지 정렬)

Phase 2 범위:
    - 기존 TBox 로드(Fuseki urn:ontology 그래프) + 정렬 제안 생성(결정론적: 정확 + difflib 유사).
    - 매핑 규칙 저장 없음(문서마다 검토, §6.3).
    - 실제 커밋/확장 반영은 preview/confirm 통합 단계에서.

무의존: 유사도는 stdlib difflib를 사용(rapidfuzz 미설치 환경 대비).
"""
import difflib
from typing import Any, Dict, List, Optional, Set

import requests

from app.core.config import settings

OWL = "http://www.w3.org/2002/07/owl#"


def _local_name(uri: str) -> str:
    return str(uri).split("/")[-1].split("#")[-1]


def _similarity(a: str, b: str) -> float:
    """대소문자 무시 문자열 유사도(0~1). stdlib difflib 기반(무의존)."""
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


class OntologyAligner:
    """구조화 문서 후보 스키마 ↔ 기존 TBox 정렬."""

    SIMILARITY_THRESHOLD = 0.80  # 이 이상이면 '유사(similar)' 후보로 제안

    def __init__(self):
        self.base_url = settings.FUSEKI_URL
        self.auth = ("admin", "admin")

    # ------------------------------------------------------------------
    # 기존 TBox 로드 (Fuseki urn:ontology:{kb_id})
    # ------------------------------------------------------------------
    def load_existing_tbox(self, kb_id: str) -> Dict[str, Dict[str, str]]:
        """승격된 TBox의 클래스/속성 로컬네임을 로드.

        반환: {"classes": {localname: uri}, "properties": {localname: uri}}
        승격 전(그래프 비어있음)이면 빈 dict들을 반환한다.
        """
        dataset = f"kb_{kb_id.replace('-', '_')}"
        graph = f"urn:ontology:{kb_id}"
        endpoint = f"{self.base_url}/{dataset}/sparql"

        classes = self._query_local_names(endpoint, graph, f"{OWL}Class")
        obj_props = self._query_local_names(endpoint, graph, f"{OWL}ObjectProperty")
        data_props = self._query_local_names(endpoint, graph, f"{OWL}DatatypeProperty")
        properties = {**obj_props, **data_props}
        return {"classes": classes, "properties": properties}

    def _query_local_names(self, endpoint: str, graph: str, rdf_type: str) -> Dict[str, str]:
        query = (
            "SELECT DISTINCT ?x WHERE { GRAPH <%s> { ?x a <%s> } }" % (graph, rdf_type)
        )
        try:
            r = requests.post(
                endpoint,
                data={"query": query},
                auth=self.auth,
                headers={"Accept": "application/sparql-results+json"},
                timeout=15,
            )
            if r.status_code != 200:
                return {}
            out: Dict[str, str] = {}
            for b in r.json().get("results", {}).get("bindings", []):
                uri = b["x"]["value"]
                out[_local_name(uri)] = uri
            return out
        except Exception:
            # 정렬 실패가 인제스트를 막지 않도록(TBox 미로드 시 '승격 안 됨'처럼 취급)
            return {}

    # ------------------------------------------------------------------
    # 후보 추출 (구조화 extractor 결과 triples에서)
    # ------------------------------------------------------------------
    @staticmethod
    def candidates_from_triples(triples: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
        """triples에서 후보 클래스/속성 집합을 뽑는다.

        - 클래스: subject_type / object_type 중 non-None, "Entity" 제외
        - 속성: predicate 중 구조 보조 술어("label","_type") 제외
        """
        classes: Set[str] = set()
        properties: Set[str] = set()
        for t in triples:
            for k in ("subject_type", "object_type"):
                v = t.get(k)
                if v and v != "Entity":
                    classes.add(v)
            p = t.get("predicate")
            if p and p not in ("label", "_type"):
                properties.add(p)
        return {"classes": classes, "properties": properties}

    # ------------------------------------------------------------------
    # 정렬(결정론적)
    # ------------------------------------------------------------------
    def align(
        self,
        candidate_classes: Set[str],
        candidate_properties: Set[str],
        existing_classes: Dict[str, str],
        existing_properties: Dict[str, str],
    ) -> Dict[str, Any]:
        """후보 ↔ 기존을 대조해 matched/similar/new로 분류하고 disjoint를 판정.

        반환:
        {
          "existing_empty": bool,          # 기존 TBox가 비어있으면 True(=미승격)
          "classes":    {matched, similar, new},
          "properties": {matched, similar, new},
          "disjoint": bool,                # 기존이 있는데 겹치는 게 하나도 없음
          "has_mismatch": bool,            # similar/new/disjoint 중 하나라도 있으면 True
        }
        matched:  [{"candidate","existing"}]
        similar:  [{"candidate","suggested","score"}]
        new:      ["candidate", ...]
        """
        existing_empty = not existing_classes and not existing_properties

        cls = self._align_group(candidate_classes, existing_classes)
        prop = self._align_group(candidate_properties, existing_properties)

        # disjoint: 기존 TBox가 있는데(=승격됨) 후보 중 어느 것도 매칭/유사가 없음
        any_overlap = bool(cls["matched"] or cls["similar"] or prop["matched"] or prop["similar"])
        has_candidates = bool(candidate_classes or candidate_properties)
        disjoint = (not existing_empty) and has_candidates and not any_overlap

        has_mismatch = bool(
            cls["similar"] or cls["new"] or prop["similar"] or prop["new"] or disjoint
        )

        return {
            "existing_empty": existing_empty,
            "classes": cls,
            "properties": prop,
            "disjoint": disjoint,
            "has_mismatch": has_mismatch,
        }

    def _align_group(
        self, candidates: Set[str], existing: Dict[str, str]
    ) -> Dict[str, List[Any]]:
        matched: List[Dict[str, str]] = []
        similar: List[Dict[str, Any]] = []
        new: List[str] = []

        # 대소문자 무시 정확 매칭용 인덱스
        existing_ci = {name.lower(): name for name in existing}

        for cand in sorted(candidates):
            if not existing:
                new.append(cand)
                continue
            # 1) 정확 매칭(대소문자 무시)
            exact = existing_ci.get(cand.lower())
            if exact is not None:
                matched.append({"candidate": cand, "existing": exact})
                continue
            # 2) 유사 매칭(difflib, 임계값 이상 중 최고 점수)
            best_name = None
            best_score = 0.0
            for name in existing:
                s = _similarity(cand, name)
                if s > best_score:
                    best_score, best_name = s, name
            if best_name is not None and best_score >= self.SIMILARITY_THRESHOLD:
                similar.append(
                    {"candidate": cand, "suggested": best_name, "score": round(best_score, 3)}
                )
            else:
                new.append(cand)

        return {"matched": matched, "similar": similar, "new": new}


# 편의 싱글턴(다른 커넥터 스타일과 일치)
ontology_aligner = OntologyAligner()
