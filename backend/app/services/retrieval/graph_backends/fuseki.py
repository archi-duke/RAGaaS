import asyncio
import os
import re
import urllib.parse
import logging
from typing import List, Dict, Any, Tuple, Optional
from .base import GraphBackend
from app.core.fuseki import fuseki_client
from app.services.retrieval.sparql_utils import escape_sparql_literal
from app.services.retrieval.query_gen_loop import QueryGenerationLoop
from app.services.retrieval.query_gen_attempt_logger import log_attempts
from app.services.retrieval.query_gen_example_memory import ExampleMemory
from app.services.embedding import embedding_service as default_embedding_service

logger = logging.getLogger(__name__)

def _compact_alias(text: str) -> str:
    from app.services.retrieval.entity_linking import _compact
    return _compact(text)


class FusekiBackend(GraphBackend):
    """Fuseki (Ontology) implementation of GraphBackend."""

    def __init__(self):
        self.namespace_relation = "http://rag.local/relation/"
        self.generator = None
        try:
            from app.services.retrieval.sparql_generator import SPARQLGenerator
            self._SPARQLGenerator = SPARQLGenerator
            print("DEBUG: [Fuseki] Doc2Onto SPARQLGenerator initialized successfully")
        except ImportError as e:
            print(f"WARNING: [Fuseki] Could not import Doc2Onto SPARQLGenerator: {e}. Using fallback logic.")
            self._SPARQLGenerator = None
        except Exception as e:
            print(f"WARNING: [Fuseki] Failed to initialize SPARQLGenerator: {e}")
            self._SPARQLGenerator = None

    async def _get_generator(self, llm_model_config: dict):
        """llm_model_config로 SPARQLGenerator 동적 생성."""
        if not self._SPARQLGenerator:
            raise ValueError("SPARQLGenerator is unavailable.")
        if not llm_model_config:
            raise ValueError("Graph query model is not configured.")
        from app.core.models_resolver import resolve_model_config
        resolved = await resolve_model_config(llm_model_config)
        api_key = resolved.get("api_key")
        extra_headers = resolved.get("extra_headers") or {}
        # 사내 게이트웨이는 헤더 인증(extra_headers)만 쓸 수 있으므로 키/헤더 중 하나면 통과.
        if not api_key and not extra_headers:
            raise ValueError("Graph query API key is not configured.")
        from app.core.llm import chat_endpoint
        return self._SPARQLGenerator(
            llm_endpoint=chat_endpoint(resolved.get("base_url")),
            llm_model=resolved.get("model") or "gpt-4o",
            api_key=api_key,
            extra_headers=extra_headers,
        )

    def _extract_entities_from_question(self, query_text: str, existing_entities: List[str]) -> List[str]:
        """질문에서 핵심 엔티티 추출. 기존 entities가 있으면 우선 사용."""
        if existing_entities:
            return existing_entities
        
        # 간단한 명사 추출 (한글 2글자 이상 단어)
        import re
        korean_words = re.findall(r'[가-힣]{2,}', query_text)
        # 불용어 제거
        stopwords = {'누구', '무엇', '어디', '언제', '어떻게', '왜', '이런', '저런', '그런', '참가자'}
        return [w for w in korean_words if w not in stopwords]

    # 엔티티 링킹 후보 최소 점수 — 이 미만이면 "못 찾음"으로 처리해 엉뚱한 앵커를 피한다.
    _MIN_LINK_SCORE = 25.0

    def _link_candidate_filter(self, var: str, entity_text: str) -> Optional[str]:
        """정규화된 라벨(?nl)에 대한 후보 수집 FILTER 절.

        라벨 쪽은 소문자 + '_'/'-' → 공백으로 정규화하고, 질문 엔티티의 각 토큰(어간화)
        포함 여부 또는 "라벨이 질문 엔티티에 포함되는" 역방향 포함을 OR 로 건다.
        넓게 모은 뒤 랭킹은 Python(score_candidate)에서 한다.
        """
        from app.services.retrieval.entity_linking import normalize_text, tokens

        norm_entity = normalize_text(entity_text)
        from app.services.retrieval.entity_linking import is_linkable
        toks = [t for t in dict.fromkeys(tokens(entity_text)) if is_linkable(t)]
        if not norm_entity:
            return None
        conds = [f'CONTAINS({var}, "{escape_sparql_literal(t)}")' for t in toks[:8]]
        conds.append(f'(STRLEN({var}) >= 3 && CONTAINS("{escape_sparql_literal(norm_entity)}", {var}))')
        # 띄어쓰기 차이 ('광전효과' ↔ 라벨 '광전 효과'): 공백 제거 후 포함 비교
        compact = norm_entity.replace(" ", "")
        if len(compact) >= 2:
            cv = f'REPLACE({var}, " ", "")'
            conds.append(f'CONTAINS({cv}, "{escape_sparql_literal(compact)}")')
        return " || ".join(conds)

    def _resolve_entity_to_uri(self, kb_id: str, entity_text: str) -> Optional[str]:
        """텍스트 엔티티를 그래프 URI로 매핑 (최고점 후보 1개). _resolve_entity_candidates 참고."""
        ranked = self._resolve_entity_candidates(kb_id, entity_text)
        return ranked[0] if ranked else None

    def _resolve_entity_candidates(self, kb_id: str, entity_text: str, k: int = 5) -> List[str]:
        """텍스트 엔티티의 그래프 URI 후보를 점수순으로 최대 k개.

        Args:
            kb_id: Knowledge Base ID
            entity_text: 검색할 엔티티 텍스트 (예: "성기훈", "Micro Frontend Architecture")

        Returns:
            발견된 URI 문자열 또는 None

        후보 수집은 정규화 라벨 기준 토큰 포함/역방향 포함으로 넓게 하고, 랭킹은
        entity_linking.score_candidate (구분자·대소문자·복수형 무시, 토큰 포함,
        서술문 노드 감점) + out-degree 보너스(관계가 실제로 달린 노드 선호)로 한다.
        구조화 문서의 'micro_frontend' 같은 snake_case 노드도 자연어로 연결된다.
        """
        try:
            from app.services.retrieval.entity_linking import is_linkable
            if not is_linkable(entity_text):
                return []
            label_filter = self._link_candidate_filter("?nl", entity_text)
            if not label_filter:
                return []

            # 1. rdfs:label 기준 후보
            label_query = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?uri ?label (COUNT(DISTINCT ?op) AS ?deg)
            FROM <urn:x-arq:UnionGraph>
            WHERE {{
              ?uri rdfs:label ?label .
              FILTER(STRSTARTS(STR(?uri), "http://rag.local/inst/"))
              FILTER(!REGEX(STR(?uri), "/inst/root_[0-9]+_"))  # 익명 구조 노드는 앵커가 될 수 없음
              BIND(REPLACE(REPLACE(LCASE(STR(?label)), "_", " "), "-", " ") AS ?nl)
              FILTER({label_filter})
              OPTIONAL {{ ?uri ?op ?oo . FILTER(?op != rdfs:label && ?op != rdf:type) }}
            }}
            GROUP BY ?uri ?label
            LIMIT 300
            """
            results = fuseki_client.query_sparql(kb_id, label_query)
            bindings = results.get("results", {}).get("bindings", [])
            ranked = self._rank_uri_bindings(entity_text, bindings, value_key="label")
            if ranked:
                return [u for u, _ in ranked[:k]]

            # 2. URI 로컬네임 기준 후보 (라벨이 없는 노드 대비)
            local_filter = self._link_candidate_filter("?nl", entity_text)
            uri_query = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?uri (COUNT(DISTINCT ?op) AS ?deg)
            FROM <urn:x-arq:UnionGraph>
            WHERE {{
              ?uri ?op ?oo .
              FILTER(STRSTARTS(STR(?uri), "http://rag.local/inst/"))
              FILTER(!REGEX(STR(?uri), "/inst/root_[0-9]+_"))  # 익명 구조 노드는 앵커가 될 수 없음
              FILTER(?op != rdfs:label && ?op != rdf:type)
              BIND(REPLACE(REPLACE(LCASE(STRAFTER(STR(?uri), "http://rag.local/inst/")), "_", " "), "-", " ") AS ?nl)
              FILTER({local_filter})
            }}
            GROUP BY ?uri
            LIMIT 300
            """
            results = fuseki_client.query_sparql(kb_id, uri_query)
            bindings = results.get("results", {}).get("bindings", [])
            ranked = self._rank_uri_bindings(entity_text, bindings, value_key=None)
            if ranked:
                return [u for u, _ in ranked[:k]]

            print(f"[Fuseki] Entity Resolution: '{entity_text}' not found in graph")
            return []

        except Exception as e:
            print(f"[Fuseki] Error resolving entity '{entity_text}': {e}")
            return []

    def _pick_best_uri_binding(self, entity_text: str, bindings: List[Dict], value_key: Optional[str]) -> Optional[str]:
        """SPARQL 바인딩 후보들에서 entity_text 와 가장 잘 매칭되는 URI 선택.

        value_key 가 지정되면 그 변수(예: label)의 값을 비교 기준으로 삼고,
        None 이면 URI 의 로컬네임(마지막 path 세그먼트, URL 디코드)을 기준으로 삼는다.
        랭킹은 entity_linking.score_candidate + 관계 수 보너스(degree_bonus, ?deg 가
        있을 때). 최고점이 _MIN_LINK_SCORE 미만이면 None.
        """
        ranked = self._rank_uri_bindings(entity_text, bindings, value_key)
        return ranked[0][0] if ranked else None

    _EQUIV_CACHE: Dict[Tuple[str, str], Tuple[float, List[str]]] = {}
    _EQUIV_TTL = 300.0
    _MAX_EQUIV = 5

    def _equivalent_uris(self, kb_id: str, uri: str) -> List[str]:
        """uri 와 같은 대상으로 볼 노드들 (자신 포함, 자신이 맨 앞). entity_linking.equivalent_names 규칙.

        추출 그래프는 '볼츠만'/'루트비히_볼츠만', '양자_전기역학'/'양자전기역학' 처럼 같은 대상을
        여러 노드로 만든다. 앵커·체인 프론티어를 묶음으로 확장해 다른 노드에 달린 사실도 조회한다.
        """
        import time
        from app.services.retrieval.entity_linking import _compact, equivalent_names, tokens

        inst = "http://rag.local/inst/"
        if not uri.startswith(inst):
            return [uri]
        key = (kb_id, uri)
        hit = self._EQUIV_CACHE.get(key)
        if hit and time.time() - hit[0] < self._EQUIV_TTL:
            return hit[1]
        name = urllib.parse.unquote(uri[len(inst):])
        toks = tokens(name)
        if not toks:
            return [uri]
        last, compact = toks[-1], _compact(name)
        q = f"""
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT DISTINCT ?u ?t
        FROM <urn:x-arq:UnionGraph>
        WHERE {{
          ?u ?p ?o .
          FILTER(STRSTARTS(STR(?u), "{inst}"))
          FILTER(!REGEX(STR(?u), "/inst/root_[0-9]+_"))
          BIND(LCASE(REPLACE(REPLACE(STRAFTER(STR(?u), "{inst}"), "_", ""), "-", "")) AS ?cu)
          FILTER(CONTAINS(LCASE(STR(?u)), "{escape_sparql_literal(last)}") || CONTAINS(?cu, "{escape_sparql_literal(compact)}"))
          OPTIONAL {{ ?u rdf:type ?t }}
        }}
        LIMIT 300
        """
        out = [uri]
        try:
            cands: Dict[str, set] = {}
            uri_of: Dict[str, str] = {}
            for b in fuseki_client.query_sparql(kb_id, q).get("results", {}).get("bindings", []):
                u = b["u"]["value"]
                t = b.get("t", {}).get("value")
                n = urllib.parse.unquote(u[len(inst):])
                uri_of.setdefault(n, u)
                cands.setdefault(n, set())
                if t:
                    cands[n].add(t.rsplit("/", 1)[-1].rsplit("#", 1)[-1])
            own = cands.pop(name, set())
            for n in equivalent_names(name, own, cands)[: self._MAX_EQUIV]:
                out.append(uri_of[n])
        except Exception as e:
            print(f"[Fuseki] equivalent lookup failed for {uri}: {e}")
        self._EQUIV_CACHE[key] = (time.time(), out)
        return out

    def _rank_uri_bindings(self, entity_text: str, bindings: List[Dict], value_key: Optional[str]
                           ) -> List[Tuple[str, float]]:
        """후보 URI 를 점수 내림차순으로 (URI 중복 제거, _MIN_LINK_SCORE 미만 제외)."""
        from app.services.retrieval.entity_linking import degree_bonus, score_candidate

        best: Dict[str, float] = {}
        for b in bindings:
            uri = b.get("uri", {}).get("value")
            if not uri:
                continue
            if value_key:
                compare_text = b.get(value_key, {}).get("value", "")
            else:
                compare_text = urllib.parse.unquote(uri.rsplit("/", 1)[-1])
            score = score_candidate(entity_text, compare_text)
            if score <= 0:
                continue
            try:
                deg = int(b.get("deg", {}).get("value", 0))
            except (TypeError, ValueError):
                deg = 0
            score += degree_bonus(deg)
            if score > best.get(uri, 0.0):
                best[uri] = score
        ranked = sorted(((u, sc) for u, sc in best.items() if sc >= self._MIN_LINK_SCORE), key=lambda x: -x[1])
        return ranked

    def _fetch_entity_predicates(self, kb_id: str, entity_uri: str) -> Dict[str, List[str]]:
        """엔티티 URI에 연결된 모든 Predicate 조회.
        
        Args:
            kb_id: Knowledge Base ID
            entity_uri: 대상 엔티티의 URI
            
        Returns:
            {"outgoing": [...], "incoming": [...]} 형태의 딕셔너리
            - outgoing: 엔티티가 Subject인 관계
            - incoming: 엔티티가 Object인 관계
        """
        try:
            # 양방향 Predicate 조회
            pred_query = f"""
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?p ?direction
            FROM <urn:x-arq:UnionGraph>
            WHERE {{
              {{
                <{entity_uri}> ?p ?o .
                BIND("outgoing" AS ?direction)
              }}
              UNION
              {{
                ?s ?p <{entity_uri}> .
                BIND("incoming" AS ?direction)
              }}
              FILTER(?p != rdf:type)
              FILTER(?p != rdfs:label)
              FILTER(?p != rdfs:comment)
              FILTER(!CONTAINS(STR(?p), "rag.local/meta"))
              FILTER(!CONTAINS(STR(?p), "rdf-syntax-ns#subject"))
              FILTER(!CONTAINS(STR(?p), "rdf-syntax-ns#object"))
              FILTER(!CONTAINS(STR(?p), "rdf-syntax-ns#predicate"))
            }}
            """
            
            results = fuseki_client.query_sparql(kb_id, pred_query)
            bindings = results.get("results", {}).get("bindings", [])
            
            predicates = {"outgoing": [], "incoming": []}
            
            for b in bindings:
                p_uri = b["p"]["value"]
                direction = b["direction"]["value"]
                
                # URI를 short form으로 변환 (예: rel:스승)
                if "/rel/" in p_uri:
                    short_p = "rel:" + p_uri.split("/rel/")[-1]
                elif "/prop/" in p_uri:
                    short_p = "prop:" + p_uri.split("/prop/")[-1]
                else:
                    short_p = p_uri.split("/")[-1]
                
                predicates[direction].append(short_p)
            
            print(f"[Fuseki] Entity Predicates for {entity_uri}: "
                  f"outgoing={len(predicates['outgoing'])}, incoming={len(predicates['incoming'])}")
            
            return predicates
            
        except Exception as e:
            print(f"[Fuseki] Error fetching predicates for {entity_uri}: {e}")
            return {"outgoing": [], "incoming": []}

    def _fetch_incoming_predicates(self, kb_id: str, entity_uri: str) -> List[str]:
        """패턴 1 전용: Object로 들어오는 Predicate만 조회 (? -> P -> O)
        
        Args:
            kb_id: Knowledge Base ID
            entity_uri: 목적어(Object) URI
            
        Returns:
            Incoming Predicate 리스트
        """
        try:
            pred_query = f"""
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?p
            FROM <urn:x-arq:UnionGraph>
            WHERE {{
              ?s ?p <{entity_uri}> .
              FILTER(?p != rdf:type)
              FILTER(?p != rdfs:label)
              FILTER(?p != rdfs:comment)
              FILTER(!CONTAINS(STR(?p), "rag.local/meta"))
              FILTER(!CONTAINS(STR(?p), "rdf-syntax-ns#"))
            }}
            """
            
            results = fuseki_client.query_sparql(kb_id, pred_query)
            bindings = results.get("results", {}).get("bindings", [])
            
            predicates = []
            for b in bindings:
                p_uri = b["p"]["value"]
                if "/rel/" in p_uri:
                    short_p = "rel:" + p_uri.split("/rel/")[-1]
                elif "/prop/" in p_uri:
                    short_p = "prop:" + p_uri.split("/prop/")[-1]
                else:
                    short_p = p_uri.split("/")[-1]
                predicates.append(short_p)
            
            print(f"[Fuseki] Incoming Predicates for {entity_uri}: {len(predicates)} found")
            return predicates
            
        except Exception as e:
            print(f"[Fuseki] Error fetching incoming predicates: {e}")
            return []

    def _fetch_outgoing_predicates(self, kb_id: str, entity_uri: str) -> List[str]:
        """패턴 3 전용: Subject에서 나가는 Predicate만 조회 (S -> P -> ?)
        
        Args:
            kb_id: Knowledge Base ID
            entity_uri: 주어(Subject) URI
            
        Returns:
            Outgoing Predicate 리스트
        """
        try:
            pred_query = f"""
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?p
            FROM <urn:x-arq:UnionGraph>
            WHERE {{
              <{entity_uri}> ?p ?o .
              FILTER(?p != rdf:type)
              FILTER(?p != rdfs:label)
              FILTER(?p != rdfs:comment)
              FILTER(!CONTAINS(STR(?p), "rag.local/meta"))
              FILTER(!CONTAINS(STR(?p), "rdf-syntax-ns#"))
            }}
            """
            
            results = fuseki_client.query_sparql(kb_id, pred_query)
            bindings = results.get("results", {}).get("bindings", [])
            
            predicates = []
            for b in bindings:
                p_uri = b["p"]["value"]
                if "/rel/" in p_uri:
                    short_p = "rel:" + p_uri.split("/rel/")[-1]
                elif "/prop/" in p_uri:
                    short_p = "prop:" + p_uri.split("/prop/")[-1]
                else:
                    short_p = p_uri.split("/")[-1]
                predicates.append(short_p)
            
            print(f"[Fuseki] Outgoing Predicates for {entity_uri}: {len(predicates)} found")
            return predicates
            
        except Exception as e:
            print(f"[Fuseki] Error fetching outgoing predicates: {e}")
            return []
            return {"outgoing": [], "incoming": []}

    def _fetch_relation_between_entities(self, kb_id: str, uri1: str, uri2: str) -> List[str]:
        """두 엔티티 사이의 직접 연결된 Predicate 조회.
        
        Args:
            kb_id: Knowledge Base ID
            uri1: 첫 번째 엔티티 URI
            uri2: 두 번째 엔티티 URI
            
        Returns:
            두 엔티티를 연결하는 Predicate 리스트
        """
        try:
            relation_query = f"""
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?p
            FROM <urn:x-arq:UnionGraph>
            WHERE {{
              {{
                <{uri1}> ?p <{uri2}> .
              }}
              UNION
              {{
                <{uri2}> ?p <{uri1}> .
              }}
              FILTER(?p != rdf:type)
              FILTER(?p != rdfs:label)
            }}
            """
            
            results = fuseki_client.query_sparql(kb_id, relation_query)
            bindings = results.get("results", {}).get("bindings", [])
            
            relations = []
            for b in bindings:
                p_uri = b["p"]["value"]
                if "/rel/" in p_uri:
                    short_p = "rel:" + p_uri.split("/rel/")[-1]
                else:
                    short_p = p_uri.split("/")[-1]
                relations.append(short_p)
            
            if relations:
                print(f"[Fuseki] Found direct relations between entities: {relations}")
            else:
                print(f"[Fuseki] No direct relation found between {uri1} and {uri2}")
            
            return relations
            
        except Exception as e:
            print(f"[Fuseki] Error fetching relation between entities: {e}")
            return []

    def _postprocess_sparql(self, raw_sparql: str, kb_id: str) -> str:
        """LLM 출력 SPARQL의 프리픽스 제거 후 표준 프리픽스+UnionGraph FROM 재주입.

        (기존 query() 인라인 로직을 그대로 이동. kb_id는 현재 사용하지 않지만
        향후 KB별 네임스페이스 커스터마이징을 위해 시그니처에 유지한다.)
        """
        print(f"[DEBUG] Step 1: Generated SPARQL received, length={len(raw_sparql)}", flush=True)

        # Remove any existing PREFIX declarations from LLM-generated query
        # to avoid conflicts with our correct prefixes
        sparql_body = re.sub(r'PREFIX\s+\w+:\s*<[^>]+>\s*', '', raw_sparql, flags=re.IGNORECASE)
        sparql_body = sparql_body.strip()
        print(f"[DEBUG] Step 2: Prefixes removed, body length={len(sparql_body)}", flush=True)

        # Ensure standard prefixes with correct namespaces
        # FIX: Must match Doc2Onto's default namespaces (example.org)
        prefixes = """
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        PREFIX inst: <http://rag.local/inst/>
        PREFIX rel: <http://rag.local/rel/>
        PREFIX prop: <http://rag.local/prop/>
        PREFIX class: <http://rag.local/class/>
        """

        # Inject FROM <urn:x-arq:UnionGraph> to search across all named graphs
        # This is crucial because Doc2Onto loads data (base.trig) into named graphs
        if re.search(r'WHERE', sparql_body, re.IGNORECASE):
            # Simple injection: replace the first 'WHERE' with 'FROM <urn:x-arq:UnionGraph> WHERE'
            print("[DEBUG] Step 3: Injecting UnionGraph...", flush=True)
            sparql_query_content = re.sub(r'WHERE', "FROM <urn:x-arq:UnionGraph>\nWHERE", sparql_body, count=1, flags=re.IGNORECASE)
        else:
            print("[DEBUG] Step 3: WHERE clause NOT found in query!", flush=True)
            sparql_query_content = sparql_body

        full_query = prefixes + sparql_query_content

        print(f"[DEBUG] Step 4: Final Query prepared, length={len(full_query)}", flush=True)
        print(f"[DEBUG] Step 4: Full Query:\n{full_query}", flush=True)

        return full_query

    def _extract_relevance_keywords(self, query_text: str, known_entity_names: List[str]) -> List[str]:
        """질문에서 관련성 체크용 핵심 키워드 추출 (엔티티명/불용어 제외).

        기존 query() 685-712행 부근 로직을 그대로 이동한 것으로, Fast Path
        relevance check와 LLM 경로 예시 저장 게이트가 동일한 로직을 공유하도록 한다.
        """
        query_tokens = query_text.replace("?", "").split()
        relation_keywords = []

        # 불용어 접두 매칭: 굴절형("누구랑","누구야","관계있어","관계는")도 걸러낸다.
        # exact-match 만 하면 필러 단어가 살아남아 정상 트리플까지 무관 판정으로 폐기됨.
        stopword_roots = ("누구", "무엇", "언제", "어디", "어떻게", "왜", "관계", "관련", "연결", "사람", "것", "무슨", "어떤")
        for t in query_tokens:
            # 조사 제거
            t_clean = t.rstrip("은는이가을를의와과로으로에게랑")
            if len(t_clean) > 1 and t_clean not in known_entity_names:
                # 질문 어미/조사 등 불용어 필터링 (접두 매칭)
                if not any(t_clean.startswith(sw) for sw in stopword_roots):
                    relation_keywords.append(t_clean)

        return relation_keywords

    def _check_triples_relevance(
        self,
        relation_keywords: List[str],
        triples: List[Dict[str, str]],
        include_subject: bool = False,
    ) -> bool:
        """추출된 키워드가 트리플 predicate/object 텍스트에 포함되는지 확인.

        기존 query() 714-725행 부근 로직을 그대로 이동. 키워드가 비어 있으면
        (원 로직대로) 관련 있는 것으로 간주한다.

        include_subject=True 이면 subject 도 매칭 대상에 포함한다. 엔티티 해석이
        실패해 엔티티가 키워드로 분류된 경우(예: '성기훈'이 주어인 트리플),
        p/o 만 보면 정답 트리플이 무관 판정되는 것을 막기 위한 옵션으로,
        ExampleMemory 저장 게이트에서만 사용한다 (Fast Path 폴백 판정은 기존
        기본값 False 를 유지해 동작 불변).
        """
        if not relation_keywords:
            return True

        for triple in triples:
            p = str(triple.get("predicate", "")).lower()
            o = str(triple.get("object", "")).lower()
            s = str(triple.get("subject", "")).lower() if include_subject else ""
            for kw in relation_keywords:
                kw = str(kw).lower()
                if kw in p or kw in o or (include_subject and kw in s):
                    return True
        return False

    async def _generate_and_execute_sparql(
        self,
        kb_id: str,
        query_text: str,
        active_generator: Any,
        entities: List[str],
        inv_mode: str,
        schema_info: Optional[Dict],
        dynamic_schema_enabled: bool,
        context_predicates: Optional[List[str]],
        custom_prompt: Optional[str],
        log_trace,
        emb_service: Any,
    ) -> Dict[str, Any]:
        """생성→후처리→실행을 QueryGenerationLoop로 감싸 실행.

        Level 2 few-shot 조회(ExampleMemory.search)를 먼저 수행하고, 이를
        generate_fn 클로저에 주입한다. 실행이 끝나면 Level 1 관측성 로깅
        (log_attempts)을 수행한다. 두 부가 기능 모두 실패해도 검색 자체를
        막지 않도록 try/except로 격리한다.

        Returns:
            {
              "query": str | None,       # 후처리(prefix+UnionGraph)까지 끝난 최종 SPARQL
              "results": list,           # bindings
              "attempts": [AttemptLog...],
              "succeeded": bool,
              "few_shot_ids": list[str],
              "raw_gen": dict,           # 마지막 시도의 SPARQLGenerator.generate() 원본 반환값
            }
        """
        few_shot: List[Dict[str, Any]] = []
        few_shot_ids: List[str] = []
        try:
            few_shot = await ExampleMemory().search(kb_id, "fuseki", query_text, emb_service)
            few_shot_ids = [ex["id"] for ex in few_shot]
        except Exception as e:
            log_trace(f"[Fuseki] WARNING: few-shot example search failed: {e}")

        last_raw_gen: Dict[str, Any] = {}

        async def generate_fn(question: str, retry_context: Optional[str]) -> Dict[str, Any]:
            nonlocal last_raw_gen

            combined_prompt = custom_prompt
            if retry_context:
                combined_prompt = f"{combined_prompt}\n\n{retry_context}" if combined_prompt else retry_context

            log_trace(f"[Fuseki] Calling LLM SPARQL Generator (retry={'yes' if retry_context else 'no'})")
            print(f"[DEBUG] Calling SPARQLGenerator.generate() with inv_mode={inv_mode}", flush=True)
            # generate() 는 동기 HTTP 호출 — 스레드로 넘겨 이벤트 루프(다른 요청)를 막지 않는다
            gen_result = await asyncio.to_thread(
                active_generator.generate,
                question=question,
                context=f"Entities: {', '.join(entities)}",
                mode="ontology",
                inverse_relation=inv_mode,
                schema_info=schema_info,
                kb_id=kb_id,
                use_dynamic_schema=dynamic_schema_enabled,
                context_predicates=context_predicates if context_predicates else None,
                custom_prompt=combined_prompt,
                few_shot_examples=few_shot or None,
            )
            print(f"[DEBUG] SPARQLGenerator returned: {gen_result}", flush=True)
            log_trace(f"[Fuseki] LLM returned: {gen_result}")
            last_raw_gen = gen_result

            raw_sparql = gen_result.get("sparql") if gen_result else None
            print(f"[DEBUG] generated_sparql type: {type(raw_sparql)}, value: {raw_sparql[:200] if raw_sparql else None}", flush=True)
            log_trace(f"[Fuseki] extracted generated_sparql: {raw_sparql}")

            if not raw_sparql:
                return {"query": None, "raw": gen_result}

            # Prepend schema usage comment for Debug Log (SPARQL 주석이므로 실행에는 영향 없음)
            if schema_info:
                raw_sparql = f"# [Used Promoted Ontology Schema]\n{raw_sparql}"
            log_trace(f"[Fuseki] Generated SPARQL:\n{raw_sparql}")

            full_query = self._postprocess_sparql(raw_sparql, kb_id)
            log_trace(f"[Fuseki] Executing SPARQL:\n{full_query}")

            return {"query": full_query, "raw": gen_result}

        async def execute_fn(full_query: str) -> List[Any]:
            print(f"[DEBUG] Step 5: Calling fuseki_client.query_sparql()...", flush=True)
            results = fuseki_client.query_sparql(kb_id, full_query)
            print(f"[DEBUG] Step 6: Got results from Fuseki", flush=True)
            bindings = results.get("results", {}).get("bindings", [])
            print(f"[DEBUG] Step 7: Bindings count: {len(bindings)}", flush=True)
            if len(bindings) > 0:
                print(f"[DEBUG] First binding: {bindings[0]}", flush=True)
            else:
                print(f"[DEBUG] No bindings found. Full results: {results}", flush=True)
            return bindings

        # 스키마 검증 힌트: 실패한 SPARQL 이 그래프에 없는 predicate 를 참조하면
        # 재시도 프롬프트에 "없는 predicate + 사용 가능 목록"을 주입한다 (실행 차단 아님).
        allowed_predicates: List[str] = []
        try:
            live = active_generator._fetch_fuseki_schema(kb_id) or {}
            allowed_predicates = live.get("predicates", []) or []
        except Exception as e:
            log_trace(f"[Fuseki] WARNING: schema fetch for validation failed: {e}")

        def schema_hint_fn(failed_query: str):
            from app.services.retrieval.query_validation import sparql_schema_hint
            return sparql_schema_hint(failed_query, allowed_predicates)

        # C 는 H·A·B·P 가 모두 안 될 때의 마지막 경로 — 재시도는 1회만 (평가에서 재시도 성공이 드물고 문항당 1~2분 소모)
        loop = QueryGenerationLoop(max_retries=1)
        loop_result = await loop.run(query_text, generate_fn, execute_fn, schema_hint_fn=schema_hint_fn)

        try:
            model_name = getattr(active_generator, "llm_model", None) or "unknown"
            await log_attempts(
                kb_id,
                "fuseki",
                query_text,
                loop_result["attempts"],
                model=model_name,
                few_shot_used=few_shot_ids,
            )
        except Exception as e:
            log_trace(f"[Fuseki] WARNING: failed to log query generation attempts: {e}")

        loop_result["few_shot_ids"] = few_shot_ids
        loop_result["raw_gen"] = last_raw_gen
        return loop_result

    # ------------------------------------------------------------------
    # 관계 타게팅 (docs/design-graph-relation-targeting.md)
    # ------------------------------------------------------------------

    _JOSAS = ["에게", "으로", "에서", "하고", "이나", "이다", "까지", "부터",
              "은", "는", "이", "가", "을", "를", "의", "와", "과", "로"]

    def _resolve_anchors(
        self, kb_id: str, query_text: str, entities: List[str], kwargs: Dict[str, Any], log_trace
    ) -> List[Tuple[str, str]]:
        """질문 엔티티 → 앵커 URI (최대 2개).

        - LLM 이 준 엔티티(primary)를 먼저 시도하고, 하나라도 연결되면 휴리스틱/spaCy/번역
          토큰으로 두 번째 앵커를 잡지 않는다 (엉뚱한 두 엔티티 관계 조회 방지).
        - 관계어 풀에 있는 단어("pros", "장점")는 앵커 후보에서 뺀다.
        - 두 번째 앵커는 그것도 primary 일 때만 인정한다 ("A와 B의 관계").
        """
        from app.services.retrieval.entity_linking import _compact

        primary = [e for e in (kwargs.get("primary_entities") or []) if e]
        if (kwargs.get("intent") or "").lower() == "class_query":
            # 유형 질문은 LLM 이 준 엔티티와 그 번역만 앵커 후보로 — spaCy/휴리스틱 토큰('가장')이
            # 문장형 값 노드에 잘못 연결되는 것 방지
            entities, query_text = list(kwargs.get("translated_entities") or []), ""
        others: List[str] = [e for e in (entities or []) if e and e not in primary]
        # 질문 텍스트의 조사 제거 토큰 (LLM 이 한글을 영어로 바꾼 경우 대비)
        for t in query_text.split():
            t_clean = t.rstrip(".,?!")
            for josa in self._JOSAS:
                if t_clean.endswith(josa) and len(t_clean) > len(josa):
                    t_clean = t_clean[: -len(josa)]
                    break
            if t_clean and len(t_clean) > 1 and t_clean not in primary and t_clean not in others:
                others.append(t_clean)

        alias_compacts = {
            _compact(a) for a in (kwargs.get("relation_aliases") or []) if isinstance(a, str)
        }
        if kwargs.get("target_class"):
            alias_compacts.add(_compact(str(kwargs["target_class"])))  # '스타일' 은 대상 유형이지 앵커가 아님
        alias_compacts.discard("")

        resolved: List[Tuple[str, str]] = []
        linking_log: List[Dict[str, str]] = []
        primary_resolved = False
        for entity in primary + others:
            is_primary = entity in primary
            if not is_primary and primary_resolved:
                continue
            if not is_primary and resolved:
                break
            if _compact(entity) in alias_compacts:
                log_trace(f"[Fuseki] Skip '{entity}' as anchor (relation word)")
                continue
            uri = self._resolve_entity_to_uri(kb_id, entity)
            if not uri or "/inst/" not in uri:
                continue
            if any(uri == u for _, u in resolved):
                primary_resolved = primary_resolved or is_primary
                continue
            if resolved and not is_primary:
                continue
            resolved.append((entity, uri))
            linking_log.append({"entity": entity, "uri": uri, "primary": is_primary})
            log_trace(f"[Fuseki] Resolved '{entity}' -> {uri}")
            primary_resolved = primary_resolved or is_primary
            if len(resolved) >= 2:
                break
        kwargs.setdefault("_reasoning", {})["linking"] = linking_log
        return resolved

    def _entity_role(self, entity_name: str, query_text: str, kwargs: Dict[str, Any]) -> str:
        """앵커 역할: LLM entity_roles 우선, 없으면 조사로 판별. 기본 subject."""
        role = (kwargs.get("entity_roles") or {}).get(entity_name)
        if role in ("subject", "object"):
            return role
        idx = query_text.find(entity_name)
        if idx != -1:
            after = query_text[idx + len(entity_name): idx + len(entity_name) + 2]
            if after.startswith(("을", "를")):
                return "object"
        return "subject"

    async def _select_paths_with_llm(
        self, query_text: str, catalog: List[Dict[str, Any]], kwargs: Dict[str, Any]
    ) -> Tuple[str, List[Dict[str, Any]], str]:
        """B 단계: 카탈로그(닫힌 집합)에서 LLM 이 경로 선택."""
        from app.core.models_resolver import resolve_model_config
        from app.core.llm import achat, no_thinking_extra_body
        from app.services.retrieval import relation_targeting as rt

        cfg = await resolve_model_config(kwargs.get("llm_model_config") or {})
        messages, items = rt.build_path_select_messages(query_text, catalog)
        content = await achat(
            cfg, messages, model=cfg.get("model"), temperature=0,
            response_format={"type": "json_object"},
            extra_body=no_thinking_extra_body(cfg.get("model")),
        )
        return rt.validate_llm_selection(rt.parse_json_loose(content), items)

    def _run_triple_query(self, kb_id: str, sparql: str, anchor_label: str, limit: Optional[int] = None):
        from app.services.retrieval import relation_targeting as rt
        res = fuseki_client.query_sparql(kb_id, sparql)
        return rt.parse_triple_bindings(res.get("results", {}).get("bindings", []), anchor_label, limit=limit)

    def _targeted_result(self, sparql: str, triples: List[Dict[str, Any]], reasoning: Dict[str, Any],
                         trace_logs: List[str]) -> Dict[str, Any]:
        from app.services.retrieval import relation_targeting as rt
        ranked = rt.rank_chunk_ids(triples)
        reasoning["sparql"] = sparql
        reasoning["triples"] = triples
        reasoning["chunks"] = ranked
        public_triples = [
            {"subject": t["subject"], "predicate": t["predicate"], "object": t["object"],
             "chunk_ids": t["chunk_ids"], "path": t["path"]}
            for t in triples
        ]
        return {
            "chunk_ids": [c["chunk_id"] for c in ranked],
            "chunk_order": "linkage",
            "sparql_query": sparql.strip(),
            "triples": public_triples,
            "found_entities": [],
            "used_fallback": False,
            "reasoning": reasoning,
            "trace_logs": trace_logs,
        }

    def _expand_anchor_equivalents(self, kb_id, catalog, selected):
        """A 선택 경로에 동치 경로를 덧붙인다 (유형 카탈로그 캐시만 사용 — 앵커 질문은 LLM 패스 유발 안 함)."""
        from app.services.retrieval import relation_targeting as rt
        cached = self._CLASS_CATALOG_CACHE.get(kb_id)
        if not cached:
            return selected, []
        equiv: Dict[str, List[str]] = {}
        for paths in cached[3].values():
            for p in paths:
                if p.get("equiv"):
                    equiv.setdefault(p["key"], []).extend(p["equiv"])
        sel_keys = {p["key"] for p in selected}
        added = []
        for p in list(selected):
            if p["dir"] != "out":
                continue
            for k in equiv.get(".".join(p["segments"]), []):
                for q in catalog:
                    if q["dir"] == "out" and ".".join(q["segments"]) == k and q["key"] not in sel_keys:
                        if len(selected) >= rt.MAX_SELECTED_PATHS:
                            break
                        selected.append(q)
                        sel_keys.add(q["key"])
                        added.append(f"{'.'.join(p['segments'])} ≡ {k}")
        return selected, added

    async def _relation_targeted_query(
        self, kb_id: str, query_text: str, resolved: List[Tuple[str, str]], kwargs: Dict[str, Any], log_trace
    ) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        """앵커가 확정된 질문의 관계 타게팅 검색.

        반환: (결과 dict | None, LLM SPARQL 생성 경로용 context_predicates)
        결과가 None 이면 호출부가 C(LLM SPARQL 생성) 경로로 진행한다.
        """
        from app.services.retrieval import relation_targeting as rt

        trace_logs = kwargs.get("_trace_logs_ref")
        reasoning: Dict[str, Any] = dict(kwargs.get("_reasoning") or {})

        # 동일 엔티티 묶음: 앵커와 같은 대상인 다른 노드도 함께 조회 (리포트에 표시)
        anchor_sets: Dict[str, List[str]] = {}
        for _, u in resolved[:2]:
            anchor_sets[u] = self._equivalent_uris(kb_id, u)
        for l in reasoning.get("linking") or []:
            eq = [x for x in anchor_sets.get(l.get("uri"), []) if x != l.get("uri")]
            if eq:
                l["equivalents"] = eq

        # 두 엔티티 관계: 양 끝 URI 를 고정한 직접 관계 조회
        if len(resolved) >= 2:
            (n1, u1), (n2, u2) = resolved[0], resolved[1]
            sparql = rt.build_pair_query(anchor_sets[u1], anchor_sets[u2])
            triples = self._run_triple_query(kb_id, sparql, "")
            log_trace(f"[Fuseki] Pair query {n1} ↔ {n2}: {len(triples)} triples")
            if triples:
                reasoning["targeting"] = {"mode": "pair", "matches": [], "selected_paths": [f"{n1} ↔ {n2}"]}
                return self._targeted_result(sparql, triples, reasoning, trace_logs), []
            # 직접 관계가 없으면 앵커별로 관계를 조회해 합친다 (E) — "A와 B는 같은 해인가", "몇 년 걸렸나" 형.
            # 비교·계산은 근거 청크를 보고 답변 LLM 이 한다.
            merged, parts, sqls = [], [], []
            for idx, (n, u) in enumerate(resolved[:2], 1):
                sub, _ = await self._relation_targeted_query(kb_id, query_text, [(n, u)], kwargs, log_trace)
                st = ((sub or {}).get("reasoning") or {}).get("targeting") or {}
                if sub and st.get("mode") in ("A", "B") and sub["reasoning"].get("triples"):
                    for t in sub["reasoning"]["triples"]:
                        merged.append({**t, "hop": idx})
                    parts += [f"{n}: {sp}" for sp in st.get("selected_paths") or []]
                    sqls.append(sub["sparql_query"])
            if merged:
                from app.services.retrieval import chain_query as cq
                log_trace(f"[Fuseki] Per-anchor query {n1} / {n2}: {len(merged)} triples")
                reasoning["targeting"] = {"mode": "E", "matches": [], "selected_paths": parts,
                                          "reason": f"{n1}와 {n2} 사이 직접 관계 없음 → 앵커별 조회"}
                ranked = cq.order_chunks_by_hop(merged)
                sparql = "\n# ---- next anchor ----\n".join(sqls)
                reasoning.update({"sparql": sparql, "triples": merged, "chunks": ranked,
                                  "chunk_order_label": "앵커별 교차 (두 엔티티의 근거 포함)"})
                public = [{"subject": t["subject"], "predicate": t["predicate"], "object": t["object"],
                           "chunk_ids": t["chunk_ids"], "path": t["path"]} for t in merged]
                return {"chunk_ids": [c["chunk_id"] for c in ranked], "chunk_order": "linkage",
                        "sparql_query": sparql, "triples": public, "found_entities": [],
                        "used_fallback": False, "reasoning": reasoning, "trace_logs": trace_logs}, []
            preds = list(set(self._fetch_outgoing_predicates(kb_id, u1) + self._fetch_incoming_predicates(kb_id, u1)
                             + self._fetch_outgoing_predicates(kb_id, u2) + self._fetch_incoming_predicates(kb_id, u2)))
            kwargs["_reasoning"] = {**reasoning, "targeting": {
                "mode": "C", "reason": f"{n1}와 {n2} 사이 직접 관계 없음 → LLM SPARQL 생성"}}
            return None, preds

        entity_name, anchor_uri = resolved[0]
        anchor_label = rt.local_name(anchor_uri)
        role = self._entity_role(entity_name, query_text, kwargs)

        anchor_set = anchor_sets.get(anchor_uri) or [anchor_uri]
        cat_res = fuseki_client.query_sparql(kb_id, rt.build_catalog_query(anchor_set))
        catalog = rt.parse_catalog(cat_res.get("results", {}).get("bindings", []))
        catalog_preds = list(dict.fromkeys(u for p in catalog for u in p["uris"]))
        log_trace(f"[Fuseki] Relation catalog for {anchor_label}: {len(catalog)} paths (role={role})")
        targeting: Dict[str, Any] = {"catalog_size": len(catalog), "matches": [], "role": role}

        intent = (kwargs.get("intent") or "").lower() or None
        selected: List[Dict[str, Any]] = []
        mode = None

        if intent == "overview":
            mode = "overview"
        else:
            primary = kwargs.get("primary_entities") or []
            resolved_names = {n for n, _ in resolved}
            unresolved = [e for e in primary if e not in resolved_names]
            pool = rt.build_alias_pool(
                kwargs.get("relation_aliases"), kwargs.get("relationship_type"), unresolved, query_text
            )
            # KB 매핑 규칙 별칭: 원래 키(advantages)로 물어도 정규화된 표준 키(pros)에 매칭
            rules = await self._load_schema_rules(kb_id)
            for a in list(pool):
                std = (rules.get("aliases") or {}).get(_compact_alias(a))
                if std and std not in pool:
                    pool.append(std)
            targeting["alias_pool"] = pool
            if pool:
                selected, matches = rt.match_paths(catalog, pool, role)
                if selected:
                    mode = "A"
                    targeting["matches"] = matches
                    selected, added = self._expand_anchor_equivalents(kb_id, catalog, selected)
                    if added:
                        targeting["equivalences"] = added
            if not selected and catalog:
                try:
                    b_mode, picked, reason = await self._select_paths_with_llm(query_text, catalog, kwargs)
                    targeting["reason"] = reason
                    log_trace(f"[Fuseki] LLM path selection: mode={b_mode}, paths={[p['key'] for p in picked]}")
                    if b_mode == "targeted":
                        mode, selected = "B", picked
                    elif b_mode == "overview":
                        mode = "overview"
                    else:
                        mode = "none"
                except Exception as e:
                    log_trace(f"[Fuseki] LLM path selection unavailable ({e}); delegating to LLM SPARQL generation")
                    kwargs["_reasoning"] = {**reasoning, "targeting": {
                        **targeting, "mode": "C", "reason": "LLM 경로 선택 호출 실패 → LLM SPARQL 생성"}}
                    return None, catalog_preds
            if not catalog:
                mode = "none"
                targeting["reason"] = "앵커에 연결된 관계 경로 없음"

        if mode == "overview":
            sparql = rt.build_overview_query(anchor_set)
            triples = self._run_triple_query(kb_id, sparql, anchor_label, limit=rt.OVERVIEW_LIMIT)
            targeting.update({"mode": "overview", "selected_paths": ["depth-1 이웃 (구조 노드 하위 제외)"]})
            reasoning["targeting"] = targeting
            return self._targeted_result(sparql, triples, reasoning, trace_logs), []

        if mode in ("A", "B") and selected:
            sparql = rt.build_targeted_query(anchor_set, selected)
            triples = self._run_triple_query(kb_id, sparql, anchor_label)
            targeting.update({"mode": mode, "selected_paths": [rt.path_label(p) for p in selected]})
            reasoning["targeting"] = targeting
            log_trace(f"[Fuseki] Targeted query ({mode}): {len(triples)} triples")
            return self._targeted_result(sparql, triples, reasoning, trace_logs), []

        # mode == none: Strict Mode — 일치하는 관계가 없으면 빈 결과 (이웃 전체 조회로 떨어지지 않음)
        targeting["mode"] = "none"
        targeting.setdefault(
            "reason", f"관계어 {targeting.get('alias_pool') or []}와 일치하는 경로 없음"
        )
        reasoning["targeting"] = targeting
        return self._targeted_result("", [], reasoning, trace_logs), []

    # ------------------------------------------------------------------
    # 다단계 질문 — 홉별 결정적 체인 (docs/design-graph-multihop-chain.md)
    # ------------------------------------------------------------------

    async def _chain_query(self, kb_id: str, query_text: str, kwargs: Dict[str, Any], log_trace
                           ) -> Optional[Dict[str, Any]]:
        from app.core.llm import achat, no_thinking_extra_body
        from app.core.models_resolver import resolve_model_config
        from app.services.retrieval import chain_query as cq
        from app.services.retrieval import relation_targeting as rt

        trace_logs = kwargs.get("_trace_logs_ref")
        reasoning: Dict[str, Any] = dict(kwargs.get("_reasoning") or {})
        schema_props: List[Dict[str, Any]] = []
        try:
            from app.models.knowledge_base import KnowledgeBase
            kb = await KnowledgeBase.get(kb_id)
            if kb and kb.schema_status == "active":
                schema_props = ((kb.promotion_metadata or {}).get("induction") or {}).get("properties") or []
        except Exception:
            pass
        vocab = cq.build_vocab(self._bindings(kb_id, cq.build_vocab_query()), schema_props)
        if not vocab:
            return None
        try:
            cfg = await resolve_model_config(kwargs.get("llm_model_config") or {})
            content = await achat(cfg, cq.build_plan_messages(query_text, vocab), model=cfg.get("model"),
                                  temperature=0, response_format={"type": "json_object"},
                                  extra_body=no_thinking_extra_body(cfg.get("model")))
        except Exception as e:
            log_trace(f"[Fuseki] Chain plan LLM unavailable ({e}) → LLM SPARQL generation")
            return None
        plan, notes = cq.validate_plan(rt.parse_json_loose(content), vocab)
        targeting: Dict[str, Any] = {"mode": "H", "catalog_size": len(vocab), "adjustments": notes}
        if plan is None:
            log_trace(f"[Fuseki] Chain plan rejected: {notes}")
            kwargs["_reasoning"] = {**reasoning, "targeting": {
                **targeting, "mode": "C", "reason": f"체인 계획 불가({'; '.join(notes[-1:])}) → LLM SPARQL 생성"}}
            return None

        cands = [u for u in self._resolve_entity_candidates(kb_id, plan["start"], k=3) if "/inst/" in u]
        if not cands:
            kwargs["_reasoning"] = {**reasoning, "targeting": {
                **targeting, "mode": "C", "reason": f"출발 엔티티 '{plan['start']}' 를 그래프에서 찾지 못함 → LLM SPARQL 생성"}}
            return None

        def run_hop(frontier: List[str], h: Dict[str, Any]):
            """홉 1회: (트리플, 쿼리들, 실제 쓴 홉, 반대 방향 재시도 여부)."""
            tag = f"hop{h['no']}"
            dirs = ["out", "in"] if h.get("both") else [h["direction"]]
            triples, qs = [], []
            for d in dirs:
                q = cq.build_hop_query(frontier, h["relations"], d, tag)
                qs.append(q)
                triples += cq.parse_hop(self._bindings(kb_id, q), h["no"])
            if not triples and not h.get("both"):
                d2 = "in" if h["direction"] == "out" else "out"
                q2 = cq.build_hop_query(frontier, h["relations"], d2, tag)
                t2 = cq.parse_hop(self._bindings(kb_id, q2), h["no"])
                if t2:
                    return t2, [q2], {**h, "direction": d2}, True
            return triples, qs, h, False

        async def repick(frontier: List[str], h: Dict[str, Any]):
            """끊긴 홉: 프론티어에 실제로 달린 관계 중에서 LLM 이 대신할 관계를 고른다."""
            opts = cq.parse_frontier_relations(self._bindings(kb_id, cq.build_frontier_relations_query(frontier)))
            if not opts:
                return None
            try:
                content = await achat(cfg, cq.build_repick_messages(query_text, h, cq.frontier_names(frontier), opts),
                                      model=cfg.get("model"), temperature=0, response_format={"type": "json_object"},
                                      extra_body=no_thinking_extra_body(cfg.get("model")))
            except Exception as e:
                log_trace(f"[Fuseki] Chain repick LLM unavailable ({e})")
                return None
            picks = cq.validate_repick(rt.parse_json_loose(content), opts)
            if not picks:
                return None
            triples, qs = [], []
            for d in ("out", "in"):
                rels = [p["relation"] for p in picks if p["direction"] == d]
                if rels:
                    q = cq.build_hop_query(frontier, rels, d, f"hop{h['no']}")
                    qs.append(q)
                    triples += cq.parse_hop(self._bindings(kb_id, q), h["no"])
            dirs = {p["direction"] for p in picks}
            h2 = {**h, "relations": [p["relation"] for p in picks], "direction": picks[0]["direction"],
                  "both": len(dirs) > 1, "repicked": True}
            return triples, qs, h2, False

        def expand(uris: List[str]) -> List[str]:
            out: List[str] = []
            for u in uris:
                for e in self._equivalent_uris(kb_id, u):
                    if e not in out:
                        out.append(e)
            return out[: cq.MAX_FRONTIER * 2]

        hops = [{**h, "no": i} for i, h in enumerate(plan["hops"], 1)]
        finals = [{**f, "no": len(hops) + 1} for f in plan["finals"]]
        repick_used = False

        # 출발 후보: 첫 홉이 성립하는 첫 후보 (링킹 1순위가 문장·복합어 노드일 때 대비)
        start_uri, frontier, first = None, [], None
        tried: List[str] = []
        for u in cands:
            fr = self._equivalent_uris(kb_id, u)
            res = run_hop(fr, hops[0])
            tried.append(rt.local_name(u))
            if res[0]:
                start_uri, frontier, first = u, fr, res
                break
        if start_uri is None:
            fr = self._equivalent_uris(kb_id, cands[0])
            res = await repick(fr, hops[0])
            repick_used = True
            if res and res[0]:
                start_uri, frontier, first = cands[0], fr, res
        if start_uri is None:
            kwargs["_reasoning"] = {**reasoning, "targeting": {
                **targeting, "mode": "C",
                "reason": f"첫 홉에서 일치 관계 없음 (출발 후보: {', '.join(tried)}) → LLM SPARQL 생성"}}
            return None
        if rt.local_name(start_uri) != tried[0]:
            notes.append(f"출발 후보 {', '.join(tried)} 중 첫 홉이 성립한 '{rt.local_name(start_uri)}' 에서 출발")
        reasoning["linking"] = [{"entity": plan["start"], "uri": start_uri, "primary": True,
                                 "equivalents": [x for x in frontier if x != start_uri]}]

        all_triples: List[Dict[str, Any]] = []
        sparqls: List[str] = []
        steps: List[str] = []
        visited = set(frontier)
        reached = 0
        for h in hops + finals:
            if not frontier:
                break
            base = frontier
            if first is not None:
                triples, qs, h, flipped = first
                first = None
            else:
                triples, qs, h, flipped = run_hop(base, h)
                if not triples and not h.get("final") and not repick_used:
                    repick_used = True
                    res = await repick(base, h)
                    if res:
                        triples, qs, h, flipped = res
            sparqls.extend(qs)
            if h.get("final"):
                nxt: List[str] = []
            else:
                nxt = expand(cq.next_frontier(triples, h["direction"], frontier=base, visited=visited))
            label = cq.hop_label(h, len(base), len(triples), len(nxt), flipped)
            if h.get("repicked"):
                label += " (계획 관계가 0건이라 노드의 실제 관계 중 재선택)"
            steps.append(label + (f" | 다음: {cq.frontier_names(nxt)}" if nxt else ""))
            log_trace(f"[Fuseki] Chain {steps[-1]}")
            all_triples.extend(triples)
            if not h.get("final"):
                if not triples:
                    break
                reached = h["no"]
                visited.update(nxt)
                frontier = nxt

        if reached == 0:
            kwargs["_reasoning"] = {**reasoning, "targeting": {
                **targeting, "mode": "C", "selected_paths": steps,
                "reason": "첫 홉에서 일치 관계 없음 → LLM SPARQL 생성"}}
            return None
        if reached < len(hops):
            targeting["warnings"] = [f"체인이 홉{reached} 까지만 이어짐 (전체 {len(hops)}홉) — 답변은 찾은 범위의 근거로 제한"]
        targeting.update({"selected_paths": steps,
                          "reason": f"출발 '{plan['start']}' → {len(hops)}홉 계획, {reached}홉 도달"})
        reasoning["targeting"] = targeting
        ranked = cq.order_chunks_by_hop(all_triples)
        sparql = "\n# ---- next hop ----\n".join(x.strip() for x in sparqls)
        reasoning.update({"sparql": sparql, "triples": all_triples, "chunks": ranked,
                          "chunk_order_label": "홉별 교차 (모든 홉의 근거 포함)"})
        public = [{"subject": t["subject"], "predicate": t["predicate"], "object": t["object"],
                   "chunk_ids": t["chunk_ids"], "path": t["path"]} for t in all_triples]
        return {"chunk_ids": [c["chunk_id"] for c in ranked], "chunk_order": "linkage",
                "sparql_query": sparql, "triples": public, "found_entities": [],
                "used_fallback": False, "reasoning": reasoning, "trace_logs": trace_logs}

    # ------------------------------------------------------------------
    # 유형 수준 질문 — 질의 계획 (docs/design-graph-class-query.md)
    # ------------------------------------------------------------------

    _CLASS_CATALOG_CACHE: Dict[str, Tuple[str, float, List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]] = {}
    _CLASS_CATALOG_TTL = 300.0
    _MAX_KINDS = 6

    def _bindings(self, kb_id: str, sparql: str) -> List[Dict[str, Any]]:
        return fuseki_client.query_sparql(kb_id, sparql).get("results", {}).get("bindings", [])

    def _is_record(self, kb_id: str, uri: str) -> bool:
        """레코드(시스템 predicate 외 outgoing 있음) 여부. 값 노드면 False."""
        from app.services.retrieval import class_query as cq
        try:
            res = fuseki_client.query_sparql(kb_id, cq.has_outgoing_query(uri))
            if "boolean" in res:
                return bool(res["boolean"])
        except Exception:
            pass
        return True  # 판별 불가 시 기존 동작(앵커 경로) 유지

    _EQUIV_LLM_CACHE: Dict[str, Tuple[List[Tuple[str, str]], List[List[str]]]] = {}
    # 재시작해도 남도록 파일에 보관 — 빈 캐시에서 유형 카탈로그를 만들면 LLM 5회로 약 35초 걸린다
    _EQUIV_LLM_CACHE_PATH = os.getenv("EQUIV_LLM_CACHE_PATH", "data/cache/equiv_llm_cache.json")
    _EQUIV_LLM_CACHE_LOADED = False

    @classmethod
    def _equiv_cache_load(cls) -> None:
        if cls._EQUIV_LLM_CACHE_LOADED:
            return
        cls._EQUIV_LLM_CACHE_LOADED = True
        try:
            import json as _json
            with open(cls._EQUIV_LLM_CACHE_PATH, encoding="utf-8") as f:
                for k, (pairs, groups) in _json.load(f).items():
                    cls._EQUIV_LLM_CACHE.setdefault(k, ([tuple(x) for x in pairs], groups))
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"equivalence LLM cache load failed: {e}")

    @classmethod
    def _equiv_cache_save(cls) -> None:
        try:
            import json as _json
            os.makedirs(os.path.dirname(cls._EQUIV_LLM_CACHE_PATH) or ".", exist_ok=True)
            tmp = cls._EQUIV_LLM_CACHE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                _json.dump({k: [list(map(list, v[0])), v[1]] for k, v in cls._EQUIV_LLM_CACHE.items()},
                           f, ensure_ascii=False)
            os.replace(tmp, cls._EQUIV_LLM_CACHE_PATH)
        except Exception as e:
            logger.warning(f"equivalence LLM cache save failed: {e}")

    @classmethod
    def invalidate_class_catalog(cls, kb_id: str) -> None:
        """인제스트 완료·규칙 변경 시 호출 — 유형 카탈로그 캐시 무효화."""
        cls._CLASS_CATALOG_CACHE.pop(kb_id, None)

    async def _equivalence_llm_pass(self, kb_id, kind_name, paths, total_members, kwargs, log_trace):
        """LLM 동치 패스 — 스키마 시그니처당 1회 (캐시). 실패 시 빈 결과."""
        from app.services.schema_alignment import equivalence as eq
        sig = f"{kb_id}:{kind_name}:{eq.catalog_signature(paths)}"
        self._equiv_cache_load()
        if sig in self._EQUIV_LLM_CACHE:
            return self._EQUIV_LLM_CACHE[sig]
        if not any(len(p.get("member_ids") or ()) < total_members for p in paths):
            self._EQUIV_LLM_CACHE[sig] = ([], [])
            return [], []
        try:
            from app.core.models_resolver import resolve_model_config
            from app.core.llm import achat, no_thinking_extra_body
            from app.services.retrieval.relation_targeting import parse_json_loose
            cfg = await resolve_model_config(kwargs.get("llm_model_config") or {})
            messages, items = eq.build_equivalence_messages(paths, total_members)
            content = await achat(cfg, messages, model=cfg.get("model"), temperature=0,
                                  response_format={"type": "json_object"},
                                  extra_body=no_thinking_extra_body(cfg.get("model")))
            result = eq.parse_llm_groups(parse_json_loose(content), items)
            log_trace(f"[Fuseki] Equivalence LLM pass ({kind_name}): {len(result[0])} path pairs, {len(result[1])} value groups")
        except Exception as e:
            log_trace(f"[Fuseki] Equivalence LLM pass skipped: {e}")
            return [], []
        self._EQUIV_LLM_CACHE[sig] = result
        self._equiv_cache_save()
        return result

    async def _class_catalog(self, kb_id: str, log_trace, kwargs: Optional[Dict[str, Any]] = None):
        """유형 + 유형별 경로 카탈로그 + 동치 묶음 (지문 + TTL 캐시)."""
        import os
        import time as _time
        from app.services.retrieval import class_query as cq
        from app.services.schema_alignment import equivalence as eq

        kwargs = kwargs or {}
        fp_rows = self._bindings(
            kb_id, "SELECT (COUNT(*) AS ?n) (COUNT(DISTINCT ?p) AS ?np) FROM <urn:x-arq:UnionGraph> WHERE { ?s ?p ?o }")
        fingerprint = "0"
        if fp_rows:
            fingerprint = f"{fp_rows[0].get('n', {}).get('value')}/{fp_rows[0].get('np', {}).get('value')}"
        cached = self._CLASS_CATALOG_CACHE.get(kb_id)
        if cached and cached[0] == fingerprint and _time.time() - cached[1] < self._CLASS_CATALOG_TTL:
            log_trace(f"[Fuseki] Class catalog cache hit ({fingerprint})")
            return cached[2], cached[3]

        rules = await self._load_schema_rules(kb_id)
        overlay = await self._load_schema_overlay(kb_id)
        use_llm = os.getenv("SCHEMA_EQUIV_LLM_AUTO_USE", "true").lower() != "false"
        kinds = cq.infer_kinds(self._bindings(kb_id, cq.build_member_query()))[: self._MAX_KINDS]
        # 사람이 고친 유형 이름·설명 (스키마 편집기, 구조화 KB) — docs/design-schema-editor.md §7
        cq.apply_kind_overlay(kinds, overlay)
        catalogs = {}
        for k in kinds:
            paths = cq.parse_kind_catalog(self._bindings(kb_id, cq.build_kind_catalog_query(k["members"])))
            cq.attach_coverage(paths, self._bindings(kb_id, cq.build_kind_path_members_query(k["members"])))
            llm_pairs, llm_vgroups = ([], [])
            if kwargs.get("llm_model_config"):
                llm_pairs, llm_vgroups = await self._equivalence_llm_pass(
                    kb_id, k["name"], paths, len(k["members"]), kwargs, log_trace)
            groups = eq.detect_path_groups(
                paths, llm_pairs=llm_pairs, rule_pairs=rules["key_pairs"],
                ignore_pairs=rules["ignore_pairs"], use_llm=use_llm)
            eq.annotate_catalog(paths, groups)
            # 값 동치: 동치 묶음(또는 단독 경로)의 합친 어휘 안에서
            by_key = {p["key"]: p for p in paths}
            seen = set()
            for p in paths:
                if p["key"] in seen:
                    continue
                grp = [p] + [by_key[x] for x in p.get("equiv") or [] if x in by_key]
                seen.update(x["key"] for x in grp)
                buckets = eq.group_value_equivalents(grp, llm_vgroups if use_llm else [], rules["value_map"])
                vmap = {}
                for bucket in buckets:
                    for v in bucket:
                        vmap[v["uri"]] = [x for x in bucket if x["uri"] != v["uri"]]
                for x in grp:
                    x["value_equiv"] = vmap
            k["equiv_groups"] = groups
            cq.apply_path_overlay(paths, overlay)
            catalogs[k["name"]] = paths
        self._CLASS_CATALOG_CACHE[kb_id] = (fingerprint, _time.time(), kinds, catalogs)
        log_trace(f"[Fuseki] Class catalog built: {[(k['name'], len(k['members']), len(k['equiv_groups'])) for k in kinds]}")
        return kinds, catalogs

    async def _load_schema_overlay(self, kb_id: str) -> Dict[str, Any]:
        """스키마 편집기 덧씌우기 (promotion_metadata.schema_overlay). 없거나 실패하면 빈 dict."""
        try:
            from app.models.knowledge_base import KnowledgeBase
            kb = await KnowledgeBase.get(kb_id)
            return ((kb.promotion_metadata or {}).get("schema_overlay") or {}) if kb else {}
        except Exception:
            return {}

    async def _load_schema_rules(self, kb_id: str) -> Dict[str, Any]:
        """KB 매핑 규칙 (Part 2). 규칙 저장소가 없거나 실패하면 빈 규칙."""
        empty = {"key_pairs": [], "ignore_pairs": [], "value_map": {}, "aliases": {}}
        try:
            from app.services.schema_alignment.service import load_rules_for_retrieval
            return await load_rules_for_retrieval(kb_id)
        except Exception:
            return empty

    async def _plan_with_llm(self, query_text, kinds, catalogs, value_hints, kwargs, retry_note=""):
        from app.core.models_resolver import resolve_model_config
        from app.core.llm import achat, no_thinking_extra_body
        from app.services.retrieval import class_query as cq
        from app.services.retrieval.relation_targeting import parse_json_loose

        cfg = await resolve_model_config(kwargs.get("llm_model_config") or {})
        hint_labels = [cq.local_name(u) for u in value_hints]
        messages = cq.build_plan_messages(query_text, kinds, catalogs, hint_labels, retry_note)
        content = await achat(
            cfg, messages, model=cfg.get("model"), temperature=0,
            response_format={"type": "json_object"},
            extra_body=no_thinking_extra_body(cfg.get("model")),
        )
        return parse_json_loose(content)

    async def _class_level_query(
        self, kb_id: str, query_text: str, value_hints: List[str], kwargs: Dict[str, Any], log_trace
    ) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        """유형 수준 질문: 카탈로그 → LLM 질의 계획 → 검증 → 컴파일·실행.

        반환: (결과 | None, C 경로용 context_predicates). None 이면 자유 Text-to-SPARQL(C).
        """
        from app.services.retrieval import class_query as cq

        trace_logs = kwargs.get("_trace_logs_ref")
        reasoning: Dict[str, Any] = dict(kwargs.get("_reasoning") or {})
        kinds, catalogs = await self._class_catalog(kb_id, log_trace, kwargs)
        all_preds = list(dict.fromkeys(u for c in catalogs.values() for p in c for u in p["uris"]))
        kind_info = [{"name": k["name"], "members": len(k["members"]), "examples": k["examples"],
                      "typed": bool(k.get("class_uri"))} for k in kinds]
        targeting: Dict[str, Any] = {
            "mode": "P", "kinds": kind_info,
            "catalog_size": sum(len(c) for c in catalogs.values()),
        }
        if not kinds:
            kwargs["_reasoning"] = {**reasoning, "targeting": {
                "mode": "C", "reason": "그래프에서 유형(레코드 집합)을 찾지 못함 → 자유 Text-to-SPARQL"}}
            return None, all_preds

        try:
            raw = await self._plan_with_llm(query_text, kinds, catalogs, value_hints, kwargs)
            checked = cq.validate_plan(raw, kinds, catalogs, value_hints)
            if checked["status"] == "reject":
                log_trace(f"[Fuseki] Plan rejected: {checked['message']} — retrying once")
                note = f"\n이전 계획이 반려됨: {checked['message']}. 목록의 번호·값만 사용해 다시 작성하라."
                raw = await self._plan_with_llm(query_text, kinds, catalogs, value_hints, kwargs, note)
                checked = cq.validate_plan(raw, kinds, catalogs, value_hints)
        except Exception as e:
            log_trace(f"[Fuseki] Plan LLM unavailable ({e}); delegating to free Text-to-SPARQL")
            kwargs["_reasoning"] = {**reasoning, "targeting": {
                **targeting, "mode": "C", "reason": "질의 계획 LLM 호출 불가 → 자유 Text-to-SPARQL"}}
            return None, all_preds

        status = checked["status"]
        targeting["raw_plan"] = raw
        log_trace(f"[Fuseki] Plan status={status} {checked.get('message', '')}")

        if status in ("reject", "unsupported"):
            why = "질의 계획으로 표현할 수 없음" if status == "unsupported" else "계획 검증 반려"
            kwargs["_reasoning"] = {**reasoning, "targeting": {
                **targeting, "mode": "C", "reason": f"{why}({checked.get('message', '')}) → 자유 Text-to-SPARQL"}}
            return None, all_preds

        if status in ("none", "zero"):
            targeting["mode"] = "P" if status == "zero" else "none"
            targeting["reason"] = checked.get("message") or "질문이 묻는 속성이 카탈로그에 없음"
            reasoning["targeting"] = targeting
            reasoning.update({"sparql": "", "triples": [], "chunks": []})
            return {
                "chunk_ids": [], "chunk_order": "linkage", "sparql_query": "", "triples": [],
                "found_entities": [], "used_fallback": False, "reasoning": reasoning,
                "result_summary": f"질의 계획 결과: 조건을 만족하는 엔티티 없음 ({targeting['reason']})",
                "trace_logs": trace_logs,
            }, []

        plan = checked["plan"]
        member_sparql = cq.compile_member_query(plan)
        entities = [cq._val(b, "e") for b in self._bindings(kb_id, member_sparql) if cq._val(b, "e")]
        sparql_parts = [f"# 1) 조건을 만족하는 엔티티\n{member_sparql}"]
        # 조건 완화: 계획 LLM 은 한 개념을 여러 신호로 풀어 AND 로 거는 경우가 있다
        # ("서비스를 빠르게 추가" → release_frequency=high AND modifiability=high). 둘 다 만족하는
        # 엔티티가 없으면 조건별 합집합(OR)으로 다시 조회하고 리포트에 남긴다. 부정 조건이 있으면 하지 않는다.
        relaxed_note = None
        if (not entities and len(plan["filters"]) >= 2 and not plan.get("aggregate")
                and all(f["op"] not in ("ne", "not_exists") for f in plan["filters"])):
            union: List[str] = []
            for f in plan["filters"]:
                q1 = cq.compile_member_query({**plan, "filters": [f]})
                for b in self._bindings(kb_id, q1):
                    e = cq._val(b, "e")
                    if e and e not in union:
                        union.append(e)
            if union:
                entities = union
                plan = {**plan, "match": "any"}
                relaxed_note = f"조건 완화: 모든 조건(AND)을 만족하는 엔티티 0개 → 조건 중 하나 이상(OR) {len(union)}개"
                sparql_parts.append("# 1-b) AND 결과 0건 → 조건별로 다시 조회해 합집합(OR)")
                log_trace(f"[Fuseki] {relaxed_note}")
        truncated = len(entities) > cq.MAX_RESULT_ENTITIES
        entities = entities[: cq.MAX_RESULT_ENTITIES]

        agg_values = None
        agg = plan.get("aggregate")
        if agg and agg["fn"] in ("count", "max", "min") and entities:
            agg_sparql = cq.compile_aggregate_query(entities, agg)
            rows = []
            for b in self._bindings(kb_id, agg_sparql):
                try:
                    rows.append((cq._val(b, "e"), float(cq._val(b, "agg") or 0)))
                except ValueError:
                    continue
            top = rows if agg.get("having") else cq.pick_top_with_ties(rows, agg["limit"])
            entities = [e for e, _ in top]
            agg_values = dict(top)
            sparql_parts.append(f"# 2) 집계\n{agg_sparql}")

        triples: List[Dict[str, Any]] = []
        if entities:
            ev_sparql = cq.compile_evidence_query(entities, plan)
            if ev_sparql:
                triples = cq.parse_evidence(self._bindings(kb_id, ev_sparql), entities)
                sparql_parts.append(f"# {len(sparql_parts) + 1}) 근거 트리플 + 청크\n{ev_sparql}")
        # 집계값을 합성 트리플로 (센 트리플들의 청크를 근거로)
        if agg_values:
            for e in entities:
                cids = sorted({c for t in triples if t["entity_uri"] == e and t["role"] == "aggregate"
                               for c in t["chunk_ids"]})
                triples.insert(0, {
                    "entity": cq.local_name(e), "entity_uri": e, "role": "aggregate",
                    "subject": cq.local_name(e), "predicate": f"{agg['fn']}({agg['path']['key']})",
                    "object": f"{agg_values[e]:g}", "path": "aggregate", "dir": "out",
                    "chunk_ids": cids, "edge_chunk_ids": [],
                })
            pos = {u: i for i, u in enumerate(entities)}
            triples.sort(key=lambda t: (pos.get(t["entity_uri"], 999),
                                        0 if t["path"] == "aggregate" else 1))

        ranked = cq.rank_chunk_ids_grouped(triples, entities)
        summary = cq.plan_summary(plan)
        warnings = self._plan_warnings(plan)
        targeting.update({
            "plan": summary,
            "selected_paths": [f"필터: {f}" for f in summary["filters"]]
                              + ([f"집계: {summary['aggregate']}"] if summary["aggregate"] else [])
                              + [f"반환: {r}" for r in summary["returns"]],
            "reason": plan.get("reason") or "",
            "adjustments": (checked.get("adjustments") or []) + ([relaxed_note] if relaxed_note else []),
            "equivalences": summary.get("equivalences") or [],
            "warnings": warnings,
            "result_entities": [cq.local_name(e) for e in entities],
            "truncated": truncated,
        })
        reasoning["targeting"] = targeting
        sparql = "\n\n".join(sparql_parts)
        reasoning.update({"sparql": sparql, "triples": triples, "chunks": ranked})
        log_trace(f"[Fuseki] Class plan: {len(entities)} entities, {len(triples)} triples, {len(ranked)} chunks")
        return {
            "chunk_ids": [c["chunk_id"] for c in ranked],
            "chunk_order": "linkage",
            "sparql_query": sparql,
            "triples": cq.triples_view(triples),
            "found_entities": [],
            "used_fallback": False,
            "reasoning": reasoning,
            "result_summary": cq.result_summary(entities, plan, agg_values, truncated)
                              + (f"\n주의: 스키마가 다른 문서의 엔티티는 결과에서 빠졌을 수 있음 ({len(warnings)}건 경고)"
                                 if warnings else ""),
            "trace_logs": trace_logs,
        }, []

    @staticmethod
    def _plan_warnings(plan: Dict[str, Any]) -> List[str]:
        """동치로 확정되지 않은 표기 혼재 값 경고 (조용한 누락을 드러냄)."""
        from app.services.schema_alignment import equivalence as eq
        views = [f["path"] for f in plan["filters"] if "values" in f]
        if plan.get("aggregate") and plan["aggregate"].get("values"):
            views.append(plan["aggregate"]["path"])
        out = []
        for v in views:
            grouped = {u for u, eqs in (v.get("value_equiv") or {}).items() if eqs}
            mixed = eq.mixed_language_values(v.get("values") or [], grouped)
            if mixed:
                out.append(f"표기 혼재 값: {v['key']} 에 {', '.join(mixed)} — 동치 미확정, 결과에서 빠질 수 있음")
        return out

    async def query(
        self,
        kb_id: str,
        entities: List[str],
        hops: int,
        query_type: str,
        relationship_keywords: List[str],
        query_text: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """Execute graph query on Fuseki using SPARQL."""
        
        chunk_ids = []
        triples = []
        sparql_query = ""
        trace_logs = []

        def log_trace(msg: str):
            trace_logs.append(msg)

        kwargs["_trace_logs_ref"] = trace_logs

        # 1. Try using SPARQLGenerator (LLM-based)
        llm_model_config = kwargs.get("llm_model_config") or {}
        active_generator = await self._get_generator(llm_model_config)
        if active_generator and query_text:
            try:
                # Determine inverse relation mode
                # Default: if not explicitly set, use 'auto'
                inv_mode = kwargs.get("inverse_extraction_mode", "auto")
                enable_inverse = kwargs.get("enable_inverse_search", True)  # 기본 ON으로 변경
                
                # If user explicitly disabled inverse search, override mode
                if not enable_inverse:
                    inv_mode = "none"
                
                # [REFAC] Internalized Prompt Mode
                # We no longer look up prompts from DB/KB/Pipeline.
                # The SPARQLGenerator will strictly use 'data/prompts/sparql_vibe_prompt.txt'.
                
                # Fetch Schema Info from DB (for static schema info if needed)
                # But we primarily rely on Dynamic Schema now.
                schema_info = None
                if kwargs.get("use_schema_mode", True):
                    try:
                        from app.models.knowledge_base import KnowledgeBase
                        kb = await KnowledgeBase.get(kb_id)
                        if kb and kb.is_promoted and kb.promotion_metadata:
                            schema_info = kb.promotion_metadata.get("schema_info")
                    except Exception as e_schema:
                        log_trace(f"[Fuseki] WARNING: Failed to fetch static schema info: {e_schema}")

                dynamic_schema_enabled = kwargs.get("use_dynamic_schema", True)
                log_trace(f"[Fuseki] Generating SPARQL using Internal Vibe Prompt | Dynamic Schema: {'ON' if dynamic_schema_enabled else 'OFF'} | KB: {kb_id}")

                # [NEW] Entity-Centric Schema Fetching
                context_predicates = []
                found_triples = []  # Fast Path에서 직접 찾은 트리플 저장
                found_uris = set()  # Fast Path에서 직접 찾은 URI 저장
                skip_llm_generation = False  # Fast Path 성공 시 True로 변경됨
                resolved_uris = []  # Entity-Centric 블록을 건너뛰어도 이후 참조가 안전하도록 기본값 보장
                entity_centric_enabled = kwargs.get("enable_entity_centric_schema", True)  # 기본 활성화
                
                # 라우팅 (docs/design-graph-relation-targeting.md, docs/design-graph-class-query.md)
                intent = (kwargs.get("intent") or "").lower()
                is_class_query = intent == "class_query"
                is_multihop_pattern = False
                chain_failed, chain_reason = False, None
                if not is_class_query:
                    # [OPTION 3] '의' x2 휴리스틱 — 유형 질문("…의 …스타일")은 제외
                    if query_text and query_text.count("의") >= 2:
                        is_multihop_pattern = True
                        log_trace(f"[Fuseki] 🔄 Multi-hop pattern detected (의 x{query_text.count('의')}). Delegating to LLM SPARQL generation.")
                    # 분석기가 멀티홉으로 판정한 질문도 LLM SPARQL 생성 경로(C)로 보낸다.
                    if query_type == "multi_hop" or intent == "multi_hop" or (kwargs.get("hop_count") or 1) >= 2:
                        if not is_multihop_pattern:
                            log_trace("[Fuseki] Multi-hop by query analysis.")
                        is_multihop_pattern = True
                    # 분석기 판정이 흔들리는 경우 보조: 관계 서술 관형절 2개 이상 ('발견한 … 제안한'),
                    # 집계형('모두', '나열')은 제외. 체인이 안 되면 앵커 조회로 넘어가므로 오판 비용은 지연뿐.
                    if not is_multihop_pattern and query_text and not re.search(r"모두|나열|몇 명", query_text):
                        from app.services.retrieval.entity_linking import relative_clause_count
                        if relative_clause_count(query_text) >= 2:
                            is_multihop_pattern = True
                            log_trace("[Fuseki] Multi-hop by relative clauses (>=2).")

                if entity_centric_enabled and query_text and is_multihop_pattern:
                    # 다단계: 홉별 결정적 체인 (H). 계획 불가·출발점 없음·첫 홉 0건이면 C 로.
                    chain_result = await self._chain_query(kb_id, query_text, kwargs, log_trace)
                    if chain_result is not None:
                        return chain_result
                    # 체인 불가 → 앵커 관계 조회(A/B/E)를 먼저 해 보고, 근거가 없을 때만 C
                    chain_failed = True
                    chain_reason = ((kwargs.get("_reasoning") or {}).get("targeting") or {}).get("reason")
                    kwargs.get("_reasoning", {}).pop("targeting", None)
                    is_multihop_pattern = False
                elif entity_centric_enabled and query_text and is_class_query and (kwargs.get("hop_count") or 1) >= 2:
                    # 유형 질문이라도 분석기가 다단계(hop≥2)로 본 질문은 체인을 먼저 시도한다
                    # ("뉴턴이 소속된 대학에 소속된 천체물리학자 가운데 …"). 안 되면 유형 경로로 계속.
                    log_trace("[Fuseki] class_query with hop_count>=2 → try chain (H) first")
                    chain_result = await self._chain_query(kb_id, query_text, kwargs, log_trace)
                    if chain_result is not None:
                        return chain_result
                    kwargs.get("_reasoning", {}).pop("targeting", None)

                if entity_centric_enabled and query_text and not is_multihop_pattern:
                    resolved_uris = self._resolve_anchors(kb_id, query_text, entities, kwargs, log_trace)
                    value_hints: List[str] = []
                    go_class = False
                    if resolved_uris and len(resolved_uris) == 1 and not self._is_record(kb_id, resolved_uris[0][1]):
                        # 앵커가 값 노드(outgoing 없음) → 결과가 아니라 조건 값. 유형 경로로.
                        # 값 힌트는 완전일치일 때만 ('규칙' → '도메인_규칙_테스트_용이' 같은 부분일치 제외)
                        from app.services.retrieval.entity_linking import _compact
                        ent, uri = resolved_uris[0]
                        go_class = True
                        link = kwargs["_reasoning"]["linking"][0]
                        if _compact(ent) == _compact(urllib.parse.unquote(uri.rsplit("/", 1)[-1])):
                            value_hints = [uri]
                            link["value_node"] = True
                        else:
                            link["value_node"] = True
                            link["hint_dropped"] = True
                        log_trace(f"[Fuseki] Anchor {uri} is a value node → class-level query (hint={'yes' if value_hints else 'no'})")
                    elif resolved_uris:
                        targeted, catalog_preds = await self._relation_targeted_query(
                            kb_id, query_text, resolved_uris, kwargs, log_trace
                        )
                        t_mode = ((targeted or {}).get("reasoning") or {}).get("targeting", {}).get("mode")
                        if targeted is not None and chain_failed:
                            tg = targeted["reasoning"].setdefault("targeting", {})
                            if targeted.get("triples"):
                                tg.setdefault("warnings", []).append(
                                    f"다단계 체인 불가({chain_reason or '-'}) → 앵커 관계 조회로 대신함 (부분 근거일 수 있음)")
                                return targeted
                            targeted, catalog_preds = None, catalog_preds  # 근거 없음 → C
                        if targeted is not None and not (is_class_query and t_mode == "none"):
                            return targeted
                        if targeted is not None:
                            # 레코드 앵커에서 일치 관계가 없고 유형 질문이면 → 유형 경로 (앵커는 값 힌트)
                            value_hints = [u for _, u in resolved_uris]
                            go_class = True
                        else:
                            context_predicates = catalog_preds
                    else:
                        go_class = True  # 앵커 없음 → 유형 경로
                    if go_class:
                        class_result, class_preds = await self._class_level_query(
                            kb_id, query_text, value_hints, kwargs, log_trace
                        )
                        if class_result is not None:
                            return class_result
                        context_predicates = class_preds or context_predicates

                # LLM 호출 (Fast Path로 이미 답을 찾은 경우 건너뜀) — QueryGenerationLoop로 감싸서
                # 생성 실패/0건 시 최대 2회까지 에러 되먹임 재시도한다.
                loop_result: Optional[Dict[str, Any]] = None
                emb_service = kwargs.get("embedding_service", default_embedding_service)
                # 결정적 경로(A/B/P/H/E)가 모두 근거를 못 찾았다. 기본 정책은 LLM SPARQL 생성(C) 대신
                # 문서 검색(V)으로 넘기는 것 — C 는 문항당 40초 이상 걸리고 정답률이 낮았다
                # (docs/design-graph-multihop-chain.md §7.9). graph_fallback="llm_sparql" 이면 기존 C.
                if not skip_llm_generation and (kwargs.get("graph_fallback") or "vector") == "vector":
                    rs = kwargs.setdefault("_reasoning", {})
                    prev = (rs.get("targeting") or {}).get("reason") or chain_reason
                    why = "그래프의 결정적 경로로 표현할 수 없거나 근거 없음"
                    rs["targeting"] = {**(rs.get("targeting") or {}), "mode": "V",
                                       "reason": f"{why}" + (f" ({prev})" if prev else "") + " → 문서 검색으로 답함"}
                    rs.setdefault("warnings", [])
                    log_trace("[Fuseki] 결정적 경로 근거 없음 → LLM SPARQL 생성(C) 대신 문서 검색(V)")
                    return {"chunk_ids": [], "sparql_query": "", "triples": [], "found_entities": [],
                            "fallback": "vector", "reasoning": rs, "trace_logs": trace_logs}
                if not skip_llm_generation:
                    log_trace(f"[Fuseki] Calling LLM SPARQL Generator (skip_llm_generation={skip_llm_generation})")

                    custom_prompt = kwargs.get("custom_query_prompt")

                    loop_result = await self._generate_and_execute_sparql(
                        kb_id=kb_id,
                        query_text=query_text,
                        active_generator=active_generator,
                        entities=entities,
                        inv_mode=inv_mode,
                        schema_info=schema_info,
                        dynamic_schema_enabled=dynamic_schema_enabled,
                        context_predicates=context_predicates,
                        custom_prompt=custom_prompt,
                        log_trace=log_trace,
                        emb_service=emb_service,
                    )
                    gen_result = loop_result.get("raw_gen") or {}
                else:
                    log_trace("[Fuseki] Skipping LLM SPARQL generation (Fast Path already provided results)")
                    gen_result = {"sparql": None}  # LLM 결과 없음을 명시

                # loop_result["query"]는 이미 _postprocess_sparql까지 끝난 최종 SPARQL이다
                # (프리픽스 제거 + 표준 프리픽스/UnionGraph 재주입).
                generated_sparql = loop_result.get("query") if loop_result else None
                log_trace(f"[Fuseki] extracted generated_sparql (postprocessed): {generated_sparql}")

            # SPARQL 실행 로직 (Fast Path 밖으로 이동)
                if generated_sparql:
                        # generated_sparql은 _generate_and_execute_sparql() 안에서
                        # QueryGenerationLoop가 이미 생성→후처리(prefix/UnionGraph)→실행까지
                        # 마친 최종 쿼리이다. 여기서는 loop_result의 bindings를 그대로 사용한다.
                        full_query = generated_sparql
                        bindings = loop_result.get("results", []) if loop_result else []

                        print(f"[DEBUG] Step 7: Bindings count: {len(bindings)}", flush=True)
                        if len(bindings) > 0:
                            print(f"[DEBUG] First binding: {bindings[0]}", flush=True)
                        else:
                            print(f"[DEBUG] No bindings found.", flush=True)
                        if bindings:
                             sparql_query = full_query

                        if bindings:
                            # Process results from generator query
                            found_entities = set()
                            # found_uris는 이미 Fast Path에서 초기화되었으므로 재선언하지 않음
                            # found_uris = set()  # <- 제거: Fast Path 데이터 보존
                        
                            for binding in bindings:
                                 for var_name, value_dict in binding.items():
                                     val = value_dict.get("value")
                                 
                                     # Collect meaningful entities
                                     if val and (val.startswith("http") or len(val) > 1):
                                         clean_val = val.split("/")[-1] if "/" in val else val
                                         if " " not in clean_val:
                                             found_entities.add(clean_val)
                                     
                                         if val.startswith("http"):
                                             found_uris.add(val)  # 기존 found_uris에 추가

                            log_trace(f"[Fuseki] Found {len(found_entities)} entities from graph: {list(found_entities)[:5]}...")
                        
                            # [NEW] Try to extract triples directly from LLM query result
                            # If the LLM followed the updated templates, it should return ?subject, ?predicate, ?object
                            real_triples = []
                            discovered_chunk_ids = set()
                        
                            for binding in bindings:
                                # Check if binding contains subject/predicate/object pattern
                                has_spo = ("subject" in binding or "s1" in binding) and ("predicate" in binding or "p1" in binding) and ("object" in binding or "o1" in binding)
                                has_spo_alt = "subjectLabel" in binding and "objectLabel" in binding
                                has_multi_hop = "s2" in binding or "midLabel" in binding
                            
                                if has_spo or has_spo_alt:
                                    # Helper function to clean URI to label
                                    def get_label(binding, *keys):
                                        for key in keys:
                                            val = binding.get(key, {})
                                            if isinstance(val, dict) and val.get("value"):
                                                result = val.get("value")
                                                return result.split("/")[-1] if "/" in result else result
                                        return None
                                
                                    # Extract 1st hop triple
                                    subj1 = get_label(binding, "subjectLabel", "startLabel", "subject", "s1")
                                    pred1 = get_label(binding, "predicate", "p1")
                                    obj1 = get_label(binding, "midLabel", "objectLabel", "object", "o1")
                                
                                    if subj1 and pred1 and obj1:
                                        real_triples.append({
                                            "subject": subj1,
                                            "predicate": pred1,
                                            "object": obj1
                                        })
                                
                                    # Extract 2nd hop triple if exists (multi-hop query)
                                    if has_multi_hop:
                                        subj2 = get_label(binding, "midLabel", "o1")  # mid becomes subject of 2nd hop
                                        pred2 = get_label(binding, "p2")
                                        obj2 = get_label(binding, "resultLabel", "o2")
                                    
                                        if subj2 and pred2 and obj2:
                                            real_triples.append({
                                                "subject": subj2,
                                                "predicate": pred2,
                                                "object": obj2
                                            })
                        
                            if real_triples:
                                log_trace(f"[Fuseki] Extracted {len(real_triples)} triples directly from LLM query result!")
                                print(f"[DEBUG FUSEKI] Direct triples: {real_triples[:3]}", flush=True)
                        
                            # [NEW] Fast Path에서 찾은 트리플 병합
                            if found_triples:
                                real_triples.extend(found_triples)
                                log_trace(f"[Fuseki] Merged {len(found_triples)} triples from Fast Path. Total: {len(real_triples)}")
                        
                            # If no direct triples found, fall back to secondary lookup
                            if not real_triples and found_uris:
                                # Construct a query to fetch triples involving these URIs
                                print(f"[DEBUG FUSEKI] found_uris for secondary lookup: {found_uris}", flush=True)
                            
                                union_clauses = []
                                for uri in found_uris:
                                    clause = f"""{{ BIND(<{uri}> AS ?target) . ?s ?p ?o . FILTER(?o = ?target) }}
                                    UNION
                                    {{ BIND(<{uri}> AS ?target) . ?s ?p ?o . FILTER(?s = ?target) }}"""
                                    union_clauses.append(clause)
                            
                                union_body = " UNION ".join(union_clauses)
                            
                                secondary_query = f"""
                                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                                PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                                SELECT DISTINCT ?s ?p ?o
                                FROM <urn:x-arq:UnionGraph>
                                WHERE {{
                                  {union_body}
                                  FILTER(?p != rdf:type)
                                  FILTER(?p != rdfs:label)
                                  FILTER(?p != rdfs:comment)
                                  FILTER(?p != rdf:subject)
                                  FILTER(?p != rdf:object)
                                  FILTER(?p != rdf:predicate)
                                }}
                                LIMIT 100
                                """

                                print(f"[DEBUG FUSEKI] Secondary Query:\n{secondary_query}", flush=True)
                                log_trace(f"[Fuseki] Executing Secondary Lookup for Real Triples...")
                                sec_results = fuseki_client.query_sparql(kb_id, secondary_query)
                                sec_bindings = sec_results.get("results", {}).get("bindings", [])
                            
                                for b in sec_bindings:
                                    s = b["s"]["value"].split("/")[-1]
                                    p = b["p"]["value"].split("/")[-1]
                                    o = b["o"]["value"].split("/")[-1]
                                    real_triples.append({
                                        "subject": s,
                                        "predicate": p,
                                        "object": o
                                    })
                            
                                log_trace(f"[Fuseki] Secondary lookup retrieved {len(real_triples)} real triples.")

                            # 근거 청크 조인 (docs/design-graph-class-query.md §6)
                            # 1) 바인딩에 s/p/o 가 있으면 그 트리플과 정확히 일치하는 statement 로 조인
                            # 2) 없으면 노드 기반 — outgoing 이 있는 노드(레코드·구조 노드)만.
                            #    공유 값 노드(high, small …)가 문서 전체 청크를 끌어오던 문제 방지.
                            from app.services.retrieval import class_query as cq
                            chunk_join_mode = None
                            try:
                                spo = cq.extract_spo_from_bindings(bindings)
                                if spo:
                                    for rb in self._bindings(kb_id, cq.build_spo_join_query(spo)):
                                        c = cq._val(rb, "chunk")
                                        if c:
                                            discovered_chunk_ids.add(c)
                                    chunk_join_mode = "spo"
                                elif found_uris:
                                    uris = [u for u in found_uris if u.startswith("http://rag.local/inst/")][:200]
                                    if uris:
                                        for rb in self._bindings(kb_id, cq.build_record_node_chunk_query(uris)):
                                            c = cq._val(rb, "chunk")
                                            if c:
                                                discovered_chunk_ids.add(c)
                                    chunk_join_mode = "node"
                                log_trace(f"[Fuseki] Chunk join ({chunk_join_mode}): {len(discovered_chunk_ids)} chunks")
                            except Exception as e:
                                log_trace(f"[Fuseki] Chunk join skipped: {e}")
                            if chunk_join_mode:
                                kwargs.setdefault("_reasoning", {})["chunk_order_label"] = (
                                    "트리플 s-p-o 정확 조인 (자유 SPARQL)" if chunk_join_mode == "spo"
                                    else "노드 연결 순 (자유 SPARQL — 트리플 단위 매핑 없음)"
                                )

                            # Use real_triples if found, otherwise fall back to dummy triples (which will fail mapping but show entity)
                            final_triples = real_triples if real_triples else triples

                            # [Level 2] LLM 생성 쿼리가 성공(1건 이상)했고 결과가 질문과 관련 있어 보이면
                            # ExampleMemory에 저장한다. 반환 결과 자체에는 영향을 주지 않는다
                            # (저장 실패는 검색 응답을 막지 않도록 격리).
                            if loop_result and loop_result.get("succeeded"):
                                try:
                                    # 저장 게이트는 엔티티를 제외하지 않는다: 질문의 어떤 내용어든
                                    # (엔티티 포함) 결과 트리플 s/p/o 에 나타나면 좋은 예시로 본다.
                                    # (엔티티 제외는 Fast Path 폴백 판정용 의미론 — 저장 게이트에
                                    # 그대로 쓰면 "성기훈은 누구랑 관계있어?"처럼 엔티티만 매칭되는
                                    # 정답 쿼리가 저장에서 탈락한다.)
                                    store_keywords = self._extract_relevance_keywords(query_text, [])
                                    if self._check_triples_relevance(store_keywords, final_triples, include_subject=True):
                                        await ExampleMemory().store(kb_id, "fuseki", query_text, full_query, emb_service)
                                except Exception as e_store:
                                    log_trace(f"[Fuseki] WARNING: failed to store query gen example: {e_store}")

                            return {
                                "chunk_ids": list(discovered_chunk_ids),  # Fuseki Reification에서 직접 추출
                                "sparql_query": full_query.strip(),
                                "triples": final_triples,
                                "found_entities": list(found_entities),
                                "reasoning": kwargs.get("_reasoning"),
                                "trace_logs": trace_logs
                            }
                        else:
                            # If inverse search is disabled and LLM query returned no results,
                            # don't fall back to generic search - return empty results
                            # UNLESS it is a promoted KB (schema_info exists), then we want fallback to capture anything.

                            if inv_mode == "none" and not schema_info:
                                return {
                                    "chunk_ids": [],
                                    "sparql_query": full_query.strip(),
                                    "triples": [],
                                    "found_entities": [],
                                    "reasoning": kwargs.get("_reasoning"),
                                "trace_logs": trace_logs
                                }
                        
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                log_trace(f"[Fuseki] Error during SPARQL generation/execution: {e}")
                log_trace(f"[Fuseki] Full traceback:\n{error_details}")
                print(f"[Fuseki] ERROR Details:\n{error_details}", flush=True)
                # Fallback continues below
        
        # [MODIFIED] Fallback Logic Removed
        # If we reached here, it means LLM failed or returned no results (and fallback is requested but we disabled regex fallback)
        
        log_trace("[Fuseki] Strict Mode: No fallback search performed.")
        return {
            "chunk_ids": [], 
            "sparql_query": sparql_query.strip() if sparql_query else "No Results / Generation Failed", 
            "triples": [], 
            "found_entities": [],
            "reasoning": kwargs.get("_reasoning"),
            "trace_logs": trace_logs
        }

