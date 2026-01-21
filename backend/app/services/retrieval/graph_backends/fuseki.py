import re
import urllib.parse
import logging
from typing import List, Dict, Any, Tuple, Optional
from .base import GraphBackend
from app.core.fuseki import fuseki_client

logger = logging.getLogger(__name__)

class FusekiBackend(GraphBackend):
    """Fuseki (Ontology) implementation of GraphBackend."""

    def __init__(self):
        self.namespace_relation = "http://rag.local/relation/"
        self.generator = None
        try:
            from app.services.retrieval.sparql_generator import SPARQLGenerator
            from app.core.config import settings
            self.generator = SPARQLGenerator(api_key=settings.OPENAI_API_KEY)
            print("DEBUG: [Fuseki] Doc2Onto SPARQLGenerator initialized successfully")
        except ImportError as e:
            print(f"WARNING: [Fuseki] Could not import Doc2Onto SPARQLGenerator: {e}. Using fallback logic.")
        except Exception as e:
            print(f"WARNING: [Fuseki] Failed to initialize SPARQLGenerator: {e}")

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

    def _resolve_entity_to_uri(self, kb_id: str, entity_text: str) -> Optional[str]:
        """텍스트 엔티티를 그래프 URI로 매핑.
        
        Args:
            kb_id: Knowledge Base ID
            entity_text: 검색할 엔티티 텍스트 (예: "성기훈", "장풍")
            
        Returns:
            발견된 URI 문자열 또는 None
        """
        try:
            # 1. rdfs:label로 검색
            label_query = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?uri
            FROM <urn:x-arq:UnionGraph>
            WHERE {{
              ?uri rdfs:label ?label .
              FILTER(CONTAINS(LCASE(STR(?label)), LCASE("{entity_text}")))
            }}
            LIMIT 1
            """
            
            results = fuseki_client.query_sparql(kb_id, label_query)
            bindings = results.get("results", {}).get("bindings", [])
            
            if bindings:
                return bindings[0]["uri"]["value"]
            
            # 2. URI 마지막 부분으로 검색 (예: inst:Seong_Gi-hun)
            uri_query = f"""
            PREFIX inst: <http://rag.local/inst/>
            SELECT DISTINCT ?uri
            FROM <urn:x-arq:UnionGraph>
            WHERE {{
              ?uri ?p ?o .
              FILTER(CONTAINS(LCASE(STR(?uri)), LCASE("{entity_text}")))
              FILTER(STRSTARTS(STR(?uri), "http://rag.local/inst/"))
            }}
            LIMIT 1
            """
            
            results = fuseki_client.query_sparql(kb_id, uri_query)
            bindings = results.get("results", {}).get("bindings", [])
            
            if bindings:
                return bindings[0]["uri"]["value"]
            
            print(f"[Fuseki] Entity Resolution: '{entity_text}' not found in graph")
            return None
            
        except Exception as e:
            print(f"[Fuseki] Error resolving entity '{entity_text}': {e}")
            return None

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

        # 1. Try using SPARQLGenerator (LLM-based)
        if self.generator and query_text:
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

                dynamic_schema_enabled = kwargs.get("use_dynamic_schema", False)
                log_trace(f"[Fuseki] Generating SPARQL using Internal Vibe Prompt | Dynamic Schema: {'ON' if dynamic_schema_enabled else 'OFF'} | KB: {kb_id}")

                # [NEW] Entity-Centric Schema Fetching
                context_predicates = []
                found_triples = []  # Fast Path에서 직접 찾은 트리플 저장
                found_uris = set()  # Fast Path에서 직접 찾은 URI 저장
                skip_llm_generation = False  # Fast Path 성공 시 True로 변경됨
                entity_centric_enabled = kwargs.get("enable_entity_centric_schema", True)  # 기본 활성화
                
                if entity_centric_enabled and query_text:
                    log_trace("[Fuseki] Entity-Centric Schema: ENABLED")
                    
                    # 1. 질문에서 엔티티 추출
                    question_entities = self._extract_entities_from_question(query_text, entities)
                    log_trace(f"[Fuseki] Extracted entities from question: {question_entities}")
                    
                    # [FIX] LLM이 한글을 영어로 변환하는 경우(예: 장풍->Jangpung) 대비
                    # 질문 텍스트에서 명사 형태(조사 제거)를 직접 추출하여 후보에 추가
                    try:
                        tokens = query_text.split()
                        for t in tokens:
                            t_clean = t.rstrip(".,?!")
                            # 기본적인 한국어 조사 제거 (가장 긴 조사부터)
                            josas = ["에게", "으로", "에서", "하고", "이나", "이다", "까지", "부터", "은", "는", "이", "가", "을", "를", "의", "와", "과", "로"]
                            for josa in josas:
                                if t_clean.endswith(josa) and len(t_clean) > len(josa):
                                    t_clean = t_clean[:-len(josa)]
                                    break
                            
                            if t_clean and len(t_clean) > 1 and t_clean not in question_entities:
                                question_entities.append(t_clean)
                        log_trace(f"[Fuseki] Expanded entities with heuristic: {question_entities}")
                    except Exception as e_heuristic:
                        log_trace(f"[Fuseki] Heuristic entity expansion failed: {e_heuristic}")

                    # 2. 엔티티를 URI로 매핑 (Instance URI만 유효)
                    resolved_uris = []
                    for entity in question_entities:  # 모든 후보 시도
                        uri = self._resolve_entity_to_uri(kb_id, entity)
                        if uri:
                            # Instance URI인지 검증 (rel:, prop:, class: 제외)
                            if "/inst/" in uri or "rag.local/inst/" in uri:
                                resolved_uris.append((entity, uri))
                                log_trace(f"[Fuseki] Resolved '{entity}' -> {uri}")
                            else:
                                log_trace(f"[Fuseki] Skipped '{entity}' -> {uri} (not an instance)")
                        
                        # 최대 2개의 유효한 엔티티만 수집
                        if len(resolved_uris) >= 2:
                            break
                    
                    # 3. Pattern 분류 및 처리
                    if resolved_uris:
                        num_entities = len(resolved_uris)
                        
                        if num_entities == 1:
                            # 단일 엔티티: 패턴 1 또는 패턴 3 구분 필요
                            entity_name, entity_uri = resolved_uris[0]
                            
                            # 질문 분석: Object인지 Subject인지 판단
                            # 개선된 휴리스틱: 엔티티명 바로 뒤의 조사 확인
                            entity_idx = query_text.find(entity_name)
                            if entity_idx != -1:
                                after_entity = query_text[entity_idx + len(entity_name):entity_idx + len(entity_name) + 2]
                                is_object_pattern = after_entity.startswith(("을", "를"))
                                is_subject_pattern = after_entity.startswith(("의", "이", "가"))
                            else:
                                is_object_pattern = False
                                is_subject_pattern = False
                            
                            if is_object_pattern:
                                # 패턴 1: ? -> P -> O (Subject 미상)
                                # 예: "장풍을 사용하는 참가자는?"
                                log_trace(f"[Fuseki] Pattern 1 detected: ? -> P -> {entity_name}")
                                
                                # [NEW] Fast Path for Pattern 1 (Incoming Triples)
                                incoming_query = f"""
                                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                                SELECT DISTINCT ?s ?p ?o ?sLabel ?oLabel
                                FROM <urn:x-arq:UnionGraph>
                                WHERE {{
                                    BIND(<{entity_uri}> AS ?o) .
                                    ?s ?p ?o .
                                    ?s rdfs:label ?sLabel .
                                    ?o rdfs:label ?oLabel .
                                    FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>)
                                }}
                                LIMIT 50
                                """
                                try:
                                    fast_results = fuseki_client.query_sparql(kb_id, incoming_query)
                                    fast_bindings = fast_results.get("results", {}).get("bindings", [])
                                    if fast_bindings:
                                        log_trace(f"[Fuseki] Pattern 1: Fast Path successful. Found {len(fast_bindings)} incoming triples.")
                                        for b in fast_bindings:
                                            p_uri = b["p"]["value"]
                                            # [FIX] UI 표시를 위해 'rel:' 접두어 제거
                                            short_p = p_uri.split("/")[-1] if "/" in p_uri else p_uri
                                            # 만약 'rel:' 같은게 붙어있으면 뗌 (예: rel:고수 -> 고수)
                                            short_p = short_p.replace("rel:", "").replace("prop:", "")
                                            
                                            found_triples.append({
                                                "subject": b["sLabel"]["value"],
                                                "predicate": short_p,
                                                "object": b["oLabel"]["value"]
                                            })
                                            found_uris.add(b["s"]["value"])
                                            found_uris.add(b["o"]["value"])
                                        skip_llm_generation = True
                                        log_trace(f"[Fuseki] Pattern 1: Fast Path complete. Skipping LLM.")
                                    else:
                                        # Fallback to predicate collection
                                        context_predicates = self._fetch_incoming_predicates(kb_id, entity_uri)
                                        log_trace(f"[Fuseki] Pattern 1 ({entity_name}): collected {len(context_predicates)} incoming predicates")
                                except Exception as e:
                                    log_trace(f"[Fuseki] Pattern 1: Fast Path failed: {e}")
                                
                            else:
                                # 패턴 3: S -> P -> ? (Object 미상) - 기본값
                                # 예: "성기훈의 후배는 누구야?"
                                log_trace(f"[Fuseki] Pattern 3 detected: {entity_name} -> P -> ?")
                                
                                # [NEW] Fast Path for Pattern 3 (Outgoing Triples)
                                outgoing_query = f"""
                                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                                SELECT DISTINCT ?s ?p ?o ?sLabel ?oLabel
                                FROM <urn:x-arq:UnionGraph>
                                WHERE {{
                                    BIND(<{entity_uri}> AS ?s) .
                                    ?s ?p ?o .
                                    ?s rdfs:label ?sLabel .
                                    ?o rdfs:label ?oLabel .
                                    FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>)
                                }}
                                LIMIT 50
                                """
                                try:
                                    fast_results = fuseki_client.query_sparql(kb_id, outgoing_query)
                                    fast_bindings = fast_results.get("results", {}).get("bindings", [])
                                    if fast_bindings:
                                        log_trace(f"[Fuseki] Pattern 3: Fast Path successful. Found {len(fast_bindings)} outgoing triples.")
                                        for b in fast_bindings:
                                            p_uri = b["p"]["value"]
                                            # [FIX] UI 표시를 위해 'rel:' 접두어 제거
                                            short_p = p_uri.split("/")[-1] if "/" in p_uri else p_uri
                                            short_p = short_p.replace("rel:", "").replace("prop:", "")

                                            found_triples.append({
                                                "subject": b["sLabel"]["value"],
                                                "predicate": short_p,
                                                "object": b["oLabel"]["value"]
                                            })
                                            found_uris.add(b["s"]["value"])
                                            found_uris.add(b["o"]["value"])
                                        skip_llm_generation = True
                                        log_trace(f"[Fuseki] Pattern 3: Fast Path complete. Skipping LLM.")
                                    else:
                                        # Fallback to predicate collection
                                        outgoing_preds = self._fetch_outgoing_predicates(kb_id, entity_uri)
                                        incoming_preds = self._fetch_incoming_predicates(kb_id, entity_uri)
                                        context_predicates = list(set(outgoing_preds + incoming_preds))
                                        log_trace(f"[Fuseki] Pattern 3 ({entity_name}): collected {len(context_predicates)} predicates (out+in)")
                                except Exception as e:
                                    log_trace(f"[Fuseki] Pattern 3: Fast Path failed: {e}")
                            
                        elif num_entities >= 2:
                            # 패턴 2: S -> ? -> O (Relation 미상)
                            # 예: "성기훈과 조상우의 관계는?"
                            entity1_name, uri1 = resolved_uris[0]
                            entity2_name, uri2 = resolved_uris[1]
                            
                            log_trace(f"[Fuseki] Pattern 2 detected: {entity1_name} -> ? -> {entity2_name}")
                            
                            # 직접 연결 확인 및 트리플 데이터 즉시 확보 (Fast Path)
                            direct_triple_query = f"""
                            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                            SELECT DISTINCT ?s ?p ?o ?sLabel ?oLabel
                            FROM <urn:x-arq:UnionGraph>
                            WHERE {{
                                {{
                                    BIND(<{uri1}> AS ?s) . BIND(<{uri2}> AS ?o) .
                                    ?s ?p ?o .
                                }}
                                UNION
                                {{
                                    BIND(<{uri2}> AS ?s) . BIND(<{uri1}> AS ?o) .
                                    ?s ?p ?o .
                                }}
                                ?s rdfs:label ?sLabel .
                                ?o rdfs:label ?oLabel .
                                FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>)
                            }}
                            """
                            try:
                                fast_results = fuseki_client.query_sparql(kb_id, direct_triple_query)
                                fast_bindings = fast_results.get("results", {}).get("bindings", [])
                                
                                if fast_bindings:
                                    log_trace(f"[Fuseki] Pattern 2: Fast Path successful. Found {len(fast_bindings)} direct triples.")
                                    # Fast Path 결과를 저장소에 미리 담아둠 (나중에 LLM 결과와 합쳐짐)
                                    for b in fast_bindings:
                                        p_uri = b["p"]["value"]
                                        # [FIX] UI 표시를 위해 'rel:' 접두어 제거
                                        short_p = p_uri.split("/")[-1] if "/" in p_uri else p_uri
                                        short_p = short_p.replace("rel:", "").replace("prop:", "")

                                        found_triples.append({
                                            "subject": b["sLabel"]["value"],
                                            "predicate": short_p,
                                            "object": b["oLabel"]["value"]
                                        })
                                        # URI도 secondary lookup을 위해 추가
                                        found_uris.add(b["s"]["value"])
                                        found_uris.add(b["o"]["value"])
                                    
                                    # Fast Path로 이미 정답을 찾았으므로 LLM 호출 건너뛰기
                                    skip_llm_generation = True
                                    log_trace(f"[Fuseki] Pattern 2: Fast Path complete. Skipping LLM generation (already have {len(found_triples)} triples).")
                                else:
                                    log_trace(f"[Fuseki] Pattern 2: No direct relation found via Fast Path. Falling back to surrounding predicates.")
                                    # 직접 연결 없으면 주변 Predicate 수집 (LLM 안내용)
                                    preds1_out = self._fetch_outgoing_predicates(kb_id, uri1)
                                    preds1_in = self._fetch_incoming_predicates(kb_id, uri1)
                                    preds2_out = self._fetch_outgoing_predicates(kb_id, uri2)
                                    preds2_in = self._fetch_incoming_predicates(kb_id, uri2)
                                    all_preds = preds1_out + preds1_in + preds2_out + preds2_in
                                    context_predicates = list(set(all_preds))
                            except Exception as e:
                                log_trace(f"[Fuseki] Pattern 2: Error in Fast Path query: {e}")
                    else:
                        log_trace("[Fuseki] Entity-Centric Schema: No entities resolved, skipping")

                # LLM 호출 (Fast Path로 이미 답을 찾은 경우 건너뜀)
                if not skip_llm_generation:
                    gen_result = self.generator.generate(
                        question=query_text,
                        context=f"Entities: {', '.join(entities)}",
                        mode="ontology",
                        inverse_relation=inv_mode,
                        # custom_prompt removed
                        schema_info=schema_info,
                        # system_prompt_override removed
                        entities=entities,
                        kb_id=kb_id,
                        use_dynamic_schema=kwargs.get("use_dynamic_schema", False),
                        context_predicates=context_predicates if context_predicates else None  # [NEW]
                    )
                else:
                    log_trace("[Fuseki] Skipping LLM SPARQL generation (Fast Path already provided results)")
                    gen_result = {"sparql": None}  # LLM 결과 없음을 명시
                
                
                generated_sparql = gen_result.get("sparql")
                
                # [NEW] Fast Path 데이터 우선 처리 (LLM 결과와 독립적)
                if skip_llm_generation and found_triples:
                    # Fast Path로 이미 트리플을 찾았으므로 바로 결과에 반영
                    log_trace(f"[Fuseki] Using Fast Path results: {len(found_triples)} triples, {len(found_uris)} URIs")
                    triples = found_triples  # 최종 결과에 직접 할당
                    
                    # Chunk ID 조회를 위해 found_uris 사용
                    if found_uris:
                        uri_list = " ".join([f"<{u}>" for u in found_uris])
                        reification_query = f"""
                        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                        PREFIX meta: <http://rag.local/meta/>
                        SELECT DISTINCT ?sourceNodeId
                        FROM <urn:x-arq:UnionGraph>
                        WHERE {{
                          VALUES ?target {{ {uri_list} }} .
                          {{
                            ?stmt rdf:type rdf:Statement ;
                                  rdf:subject ?target ;
                                  meta:sourceNodeId ?sourceNodeId .
                          }} UNION {{
                            ?stmt rdf:type rdf:Statement ;
                                  rdf:object ?target ;
                                  meta:sourceNodeId ?sourceNodeId .
                          }}
                        }}
                        LIMIT 100
                        """
                        try:
                            reif_results = fuseki_client.query_sparql(kb_id, reification_query)
                            reif_bindings = reif_results.get("results", {}).get("bindings", [])
                            for rb in reif_bindings:
                                if "sourceNodeId" in rb:
                                    node_id = rb["sourceNodeId"]["value"]
                                    if node_id:
                                        chunk_ids.append(node_id)
                            log_trace(f"[Fuseki] Fast Path: Found {len(chunk_ids)} chunk IDs via reification")
                        except Exception as e:
                            log_trace(f"[Fuseki] Fast Path: Reification query failed: {e}")
                    
                    # Fast Path 성공 시 즉시 결과 반환
                    log_trace(f"[Fuseki] Fast Path complete. Returning {len(triples)} triples and {len(chunk_ids)} chunks.")
                    return {
                        "chunk_ids": chunk_ids,
                        "sparql_query": "-- FAST PATH BYPASS (Direct Relationship Found) --", 
                        "triples": triples,
                        "found_entities": [t["subject"] for t in triples] + [t["object"] for t in triples],
                        "used_fallback": False,
                        "trace_logs": trace_logs
                    }
                
                if generated_sparql:
                    # Prepend schema usage comment for Debug Log
                    if schema_info:
                         generated_sparql = f"# [Used Promoted Ontology Schema]\n{generated_sparql}"

                    log_trace(f"[Fuseki] Generated SPARQL:\n{generated_sparql}")
                    
                    # Remove any existing PREFIX declarations from LLM-generated query
                    # to avoid conflicts with our correct prefixes
                    sparql_body = re.sub(r'PREFIX\s+\w+:\s*<[^>]+>\s*', '', generated_sparql, flags=re.IGNORECASE)
                    sparql_body = sparql_body.strip()
                    
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
                        print("[DEBUG FUSEKI] Injecting UnionGraph...", flush=True)
                        sparql_query_content = re.sub(r'WHERE', "FROM <urn:x-arq:UnionGraph>\nWHERE", sparql_body, count=1, flags=re.IGNORECASE)
                    else:
                        print("[DEBUG FUSEKI] WHERE clause NOT found in query!", flush=True)
                        sparql_query_content = sparql_body

                    full_query = prefixes + sparql_query_content
                    
                    print(f"[DEBUG FUSEKI] Final Query:\n{full_query}", flush=True)
                    log_trace(f"[Fuseki] Executing SPARQL:\n{full_query}")
                    
                    # Execute
                    results = fuseki_client.query_sparql(kb_id, full_query)
                    bindings = results.get("results", {}).get("bindings", [])
                    
                    print(f"[DEBUG FUSEKI] Results count: {len(bindings)}", flush=True)
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

                        # [MOVED & IMPROVED] Query Reification for sourceNodeId if ANY URIs found
                        # This should run even if real_triples were extracted directly from LLM
                        if found_uris:
                            # Optimize: Use VALUES for faster filtering
                            uri_list = " ".join([f"<{u}>" for u in found_uris])
                            
                            reification_query = f"""
                            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                            PREFIX meta: <http://rag.local/meta/>
                            SELECT DISTINCT ?sourceNodeId
                            FROM <urn:x-arq:UnionGraph>
                            WHERE {{
                              VALUES ?target {{ {uri_list} }} .
                              {{
                                ?stmt rdf:type rdf:Statement ;
                                      rdf:subject ?target ;
                                      meta:sourceNodeId ?sourceNodeId .
                              }} UNION {{
                                ?stmt rdf:type rdf:Statement ;
                                      rdf:object ?target ;
                                      meta:sourceNodeId ?sourceNodeId .
                              }}
                            }}
                            LIMIT 100
                            """
                            
                            print(f"[DEBUG FUSEKI] Reification Query for sourceNodeId...", flush=True)
                            try:
                                reif_results = fuseki_client.query_sparql(kb_id, reification_query)
                                reif_bindings = reif_results.get("results", {}).get("bindings", [])
                                
                                for rb in reif_bindings:
                                    if "sourceNodeId" in rb:
                                        node_id = rb["sourceNodeId"]["value"]
                                        if node_id:
                                            discovered_chunk_ids.add(node_id)
                                
                                log_trace(f"[Fuseki] Found {len(discovered_chunk_ids)} unique sourceNodeIds from Reification")
                            except Exception as e:
                                log_trace(f"[Fuseki] Warning: Reification query failed: {e}")

                        # Use real_triples if found, otherwise fall back to dummy triples (which will fail mapping but show entity)
                        final_triples = real_triples if real_triples else triples

                        return {
                            "chunk_ids": list(discovered_chunk_ids),  # Fuseki Reification에서 직접 추출
                            "sparql_query": generated_sparql.strip(),
                            "triples": final_triples,
                            "found_entities": list(found_entities),
                            "trace_logs": trace_logs
                        }
                    else:
                        # If inverse search is disabled and LLM query returned no results,
                        # don't fall back to generic search - return empty results
                        # UNLESS it is a promoted KB (schema_info exists), then we want fallback to capture anything.
                
                        if inv_mode == "none" and not schema_info:
                            return {
                                "chunk_ids": [],
                                "sparql_query": generated_sparql.strip(),
                                "triples": [],
                                "found_entities": [],
                                "trace_logs": trace_logs
                            }
                        
            except Exception as e:
                log_trace(f"[Fuseki] Error during SPARQL generation/execution: {e}")
                # Fallback continues below
        
        # [MODIFIED] Fallback Logic Removed
        # If we reached here, it means LLM failed or returned no results (and fallback is requested but we disabled regex fallback)
        
        log_trace("[Fuseki] Strict Mode: No fallback search performed.")
        return {
            "chunk_ids": [], 
            "sparql_query": sparql_query.strip() if sparql_query else "No Results / Generation Failed", 
            "triples": [], 
            "found_entities": [],
            "trace_logs": trace_logs
        }

