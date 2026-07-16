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
        if not api_key:
            raise ValueError("Graph query API key is not configured.")
        base_url = resolved.get("base_url")
        endpoint = f"{base_url.rstrip('/')}/chat/completions" if base_url else None
        return self._SPARQLGenerator(
            api_key=api_key,
            llm_endpoint=endpoint,
            llm_model=resolved.get("model") or "gpt-4o",
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

    def _resolve_entity_to_uri(self, kb_id: str, entity_text: str) -> Optional[str]:
        """텍스트 엔티티를 그래프 URI로 매핑.
        
        Args:
            kb_id: Knowledge Base ID
            entity_text: 검색할 엔티티 텍스트 (예: "성기훈", "장풍")
            
        Returns:
            발견된 URI 문자열 또는 None
        """
        try:
            # SPARQL 문자열 리터럴에 삽입하기 전 이스케이프 (원본 entity_text는 로깅용으로 보존)
            safe_entity_text = escape_sparql_literal(entity_text)

            # 1. rdfs:label로 검색 — LIMIT 1 임의 매치 대신 후보를 모아 랭킹한다.
            #    (부분매칭은 "성기훈" → "성기훈"/"기훈"/"성기훈의 어머니"/"기훈에게 …" 등
            #     여러 후보를 만들며, 임의 첫 매치는 긴 노이즈 노드를 앵커로 잡을 수 있다.)
            label_query = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?uri ?label
            FROM <urn:x-arq:UnionGraph>
            WHERE {{
              ?uri rdfs:label ?label .
              FILTER(CONTAINS(LCASE(STR(?label)), LCASE("{safe_entity_text}")))
            }}
            LIMIT 50
            """

            results = fuseki_client.query_sparql(kb_id, label_query)
            bindings = results.get("results", {}).get("bindings", [])

            best_uri = self._pick_best_uri_binding(entity_text, bindings, value_key="label")
            if best_uri:
                return best_uri

            # 2. URI 마지막 부분으로 검색 (예: inst:Seong_Gi-hun) — 동일하게 랭킹 적용.
            #    URI 로컬네임을 비교 대상으로 삼는다.
            uri_query = f"""
            PREFIX inst: <http://rag.local/inst/>
            SELECT DISTINCT ?uri
            FROM <urn:x-arq:UnionGraph>
            WHERE {{
              ?uri ?p ?o .
              FILTER(CONTAINS(LCASE(STR(?uri)), LCASE("{safe_entity_text}")))
              FILTER(STRSTARTS(STR(?uri), "http://rag.local/inst/"))
            }}
            LIMIT 50
            """

            results = fuseki_client.query_sparql(kb_id, uri_query)
            bindings = results.get("results", {}).get("bindings", [])

            best_uri = self._pick_best_uri_binding(entity_text, bindings, value_key=None)
            if best_uri:
                return best_uri

            print(f"[Fuseki] Entity Resolution: '{entity_text}' not found in graph")
            return None

        except Exception as e:
            print(f"[Fuseki] Error resolving entity '{entity_text}': {e}")
            return None

    def _pick_best_uri_binding(self, entity_text: str, bindings: List[Dict], value_key: Optional[str]) -> Optional[str]:
        """SPARQL 바인딩 후보들에서 entity_text 와 가장 잘 매칭되는 URI 선택.

        value_key 가 지정되면 그 변수(예: label)의 값을 비교 기준으로 삼고,
        None 이면 URI 의 로컬네임(마지막 path 세그먼트, '_'→' ')을 기준으로 삼는다.
        랭킹은 entity_linking.score_candidate (완전일치 > 접두 > 부분포함, 길이 근접
        보너스)를 따른다. 매칭 후보가 없으면 None.
        """
        from app.services.retrieval.entity_linking import score_candidate

        best_uri, best_score = None, 0.0
        for b in bindings:
            uri = b.get("uri", {}).get("value")
            if not uri:
                continue
            if value_key:
                compare_text = b.get(value_key, {}).get("value", "")
            else:
                local = uri.rsplit("/", 1)[-1]
                compare_text = local.replace("_", " ")
            score = score_candidate(entity_text, compare_text)
            if score > best_score:
                best_uri, best_score = uri, score
        return best_uri

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

        for t in query_tokens:
            # 조사 제거
            t_clean = t.rstrip("은는이가을를의와과로으로에게")
            if len(t_clean) > 1 and t_clean not in known_entity_names:
                # 질문 어미/조사 등 불용어 필터링 (간단히)
                if t_clean not in ["누구", "무엇", "언제", "어디", "어떻게", "관계", "사람", "것"]:
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
            p = triple.get("predicate", "")
            o = triple.get("object", "")
            s = triple.get("subject", "") if include_subject else ""
            for kw in relation_keywords:
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
            gen_result = active_generator.generate(
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

        loop = QueryGenerationLoop(max_retries=2)
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
                
                # [OPTION 3] Multi-hop Pattern Detection - Skip Fast Path if multi-hop detected
                is_multihop_pattern = False
                if query_text and "의" in query_text:
                    count_ui = query_text.count("의")
                    if count_ui >= 2:
                        is_multihop_pattern = True
                        log_trace(f"[Fuseki] 🔄 Multi-hop pattern detected (의 x{count_ui}). Skipping Fast Path, delegating to LLM.")
                
                if entity_centric_enabled and query_text and not is_multihop_pattern:
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
                            # SPARQL 문자열 리터럴 삽입용 이스케이프 (entity_name 원본은 조사 판별 등에 계속 사용)
                            safe_entity_name = escape_sparql_literal(entity_name)

                            # 질문 분석: Object인지 Subject인지 판단
                            # 1차: LLM 이 판별한 엔티티 역할(entity_roles), 없으면 조사(Josa) 폴백
                            entity_roles = kwargs.get("entity_roles") or {}
                            role = entity_roles.get(entity_name)
                            if role == "object":
                                is_object_pattern, is_subject_pattern = True, False
                                log_trace(f"[Fuseki] Role by LLM: '{entity_name}' = object → Pattern 1")
                            elif role == "subject":
                                is_object_pattern, is_subject_pattern = False, True
                                log_trace(f"[Fuseki] Role by LLM: '{entity_name}' = subject → Pattern 3")
                            else:
                                # 폴백: 엔티티명 바로 뒤의 조사 확인 (기존 동작 불변)
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
                                
                                # [UPGRADED] Fast Path for Pattern 1 (Bidirectional + Partial Match)
                                # 양방향 조회 + 부분 일치: "장풍"을 검색하면 "장풍의 고수", "장풍의 창시자" 등도 포함
                                bidirectional_query = f"""
                                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                                SELECT DISTINCT ?s ?p ?o ?sLabel ?oLabel
                                FROM <urn:x-arq:UnionGraph>
                                WHERE {{
                                    {{
                                        # Incoming: ?s -> ?p -> 엔티티 (엔티티가 목적어, 양방향 부분 일치)
                                        ?s ?p ?o .
                                        ?o rdfs:label ?oLabel .
                                        FILTER(CONTAINS(LCASE(?oLabel), LCASE("{safe_entity_name}")) || CONTAINS(LCASE("{safe_entity_name}"), LCASE(?oLabel)))
                                        FILTER(STRLEN(?oLabel) > 1)
                                    }}
                                    UNION
                                    {{
                                        # Outgoing: 엔티티 -> ?p -> ?o (엔티티가 주어, 양방향 부분 일치)
                                        ?s ?p ?o .
                                        ?s rdfs:label ?sLabel .
                                        FILTER(CONTAINS(LCASE(?sLabel), LCASE("{safe_entity_name}")) || CONTAINS(LCASE("{safe_entity_name}"), LCASE(?sLabel)))
                                        FILTER(STRLEN(?sLabel) > 1)
                                    }}
                                    OPTIONAL {{ ?s rdfs:label ?sLabel }}
                                    OPTIONAL {{ ?o rdfs:label ?oLabel }}
                                    # Reification 메타데이터 제외 (rdf:subject, rdf:predicate, rdf:object)
                                    FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>)
                                    FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#subject>)
                                    FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate>)
                                    FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#object>)
                                    FILTER(?p != <http://www.w3.org/2000/01/rdf-schema#label>)
                                }}
                                LIMIT 100
                                """
                                try:
                                    log_trace(f"[Fuseki] Pattern 1 Bidirectional Fast Path SPARQL:\n{bidirectional_query}")
                                    fast_results = fuseki_client.query_sparql(kb_id, bidirectional_query)
                                    fast_bindings = fast_results.get("results", {}).get("bindings", [])
                                    if fast_bindings:
                                        log_trace(f"[Fuseki] Pattern 1: Bidirectional Fast Path successful. Found {len(fast_bindings)} triples (incoming + outgoing).")
                                        for b in fast_bindings:
                                            p_uri = b["p"]["value"]
                                            # [FIX] UI 표시를 위해 'rel:' 접두어 제거
                                            short_p = p_uri.split("/")[-1] if "/" in p_uri else p_uri
                                            # 만약 'rel:' 같은게 붙어있으면 뗌 (예: rel:고수 -> 고수)
                                            short_p = short_p.replace("rel:", "").replace("prop:", "")
                                            
                                            # [FIX] Label이 없을 경우 URI에서 추출 (KeyError 방지)
                                            s_label = b.get("sLabel", {}).get("value") or (b["s"]["value"].split("/")[-1].split("#")[-1])
                                            o_label = b.get("oLabel", {}).get("value") or (b["o"]["value"].split("/")[-1].split("#")[-1])

                                            found_triples.append({
                                                "subject": s_label,
                                                "predicate": short_p,
                                                "object": o_label
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
                                
                                # [UPGRADED] Fast Path for Pattern 3 (Bidirectional + Partial Match)
                                # 양방향 조회 + 부분 일치: "장풍"을 검색하면 "장풍의 고수" 등도 포함
                                bidirectional_query = f"""
                                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                                SELECT DISTINCT ?s ?p ?o ?sLabel ?oLabel
                                FROM <urn:x-arq:UnionGraph>
                                WHERE {{
                                    {{
                                        # Outgoing: 엔티티 -> ?p -> ?o (엔티티가 주어, 양방향 부분 일치)
                                        ?s ?p ?o .
                                        ?s rdfs:label ?sLabel .
                                        FILTER(CONTAINS(LCASE(?sLabel), LCASE("{safe_entity_name}")) || CONTAINS(LCASE("{safe_entity_name}"), LCASE(?sLabel)))
                                        FILTER(STRLEN(?sLabel) > 1)
                                    }}
                                    UNION
                                    {{
                                        # Incoming: ?s -> ?p -> 엔티티 (엔티티가 목적어, 양방향 부분 일치)
                                        ?s ?p ?o .
                                        ?o rdfs:label ?oLabel .
                                        FILTER(CONTAINS(LCASE(?oLabel), LCASE("{safe_entity_name}")) || CONTAINS(LCASE("{safe_entity_name}"), LCASE(?oLabel)))
                                        FILTER(STRLEN(?oLabel) > 1)
                                    }}
                                    OPTIONAL {{ ?s rdfs:label ?sLabel }}
                                    OPTIONAL {{ ?o rdfs:label ?oLabel }}
                                    # Reification 메타데이터 제외
                                    FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>)
                                    FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#subject>)
                                    FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate>)
                                    FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#object>)
                                    FILTER(?p != <http://www.w3.org/2000/01/rdf-schema#label>)
                                }}
                                LIMIT 100
                                """
                                try:
                                    log_trace(f"[Fuseki] Pattern 3 Bidirectional Fast Path SPARQL:\n{bidirectional_query}")
                                    fast_results = fuseki_client.query_sparql(kb_id, bidirectional_query)
                                    fast_bindings = fast_results.get("results", {}).get("bindings", [])
                                    if fast_bindings:
                                        log_trace(f"[Fuseki] Pattern 3: Bidirectional Fast Path successful. Found {len(fast_bindings)} triples (outgoing + incoming).")
                                        for b in fast_bindings:
                                            p_uri = b["p"]["value"]
                                            # [FIX] UI 표시를 위해 'rel:' 접두어 제거
                                            short_p = p_uri.split("/")[-1] if "/" in p_uri else p_uri
                                            short_p = short_p.replace("rel:", "").replace("prop:", "")

                                            # [FIX] Label이 없을 경우 URI에서 추출 (KeyError 방지)
                                            s_label = b.get("sLabel", {}).get("value") or (b["s"]["value"].split("/")[-1].split("#")[-1])
                                            o_label = b.get("oLabel", {}).get("value") or (b["o"]["value"].split("/")[-1].split("#")[-1])

                                            found_triples.append({
                                                "subject": s_label,
                                                "predicate": short_p,
                                                "object": o_label
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
                            # SPARQL 문자열 리터럴 삽입용 이스케이프 (원본은 로깅 등에 계속 사용)
                            safe_entity1_name = escape_sparql_literal(entity1_name)
                            safe_entity2_name = escape_sparql_literal(entity2_name)

                            log_trace(f"[Fuseki] Pattern 2 detected: {entity1_name} -> ? -> {entity2_name}")
                            
                            # 직접 연결 확인 및 트리플 데이터 즉시 확보 (Fast Path with Partial Match)
                            direct_triple_query = f"""
                            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                            SELECT DISTINCT ?s ?p ?o ?sLabel ?oLabel
                            FROM <urn:x-arq:UnionGraph>
                            WHERE {{
                                {{
                                    # Entity1 -> Entity2 (양방향 부분 일치)
                                    ?s ?p ?o .
                                    ?s rdfs:label ?sLabel .
                                    ?o rdfs:label ?oLabel .
                                    FILTER(CONTAINS(LCASE(?sLabel), LCASE("{safe_entity1_name}")) || CONTAINS(LCASE("{safe_entity1_name}"), LCASE(?sLabel)))
                                    FILTER(CONTAINS(LCASE(?oLabel), LCASE("{safe_entity2_name}")) || CONTAINS(LCASE("{safe_entity2_name}"), LCASE(?oLabel)))
                                    FILTER(STRLEN(?sLabel) > 1)
                                    FILTER(STRLEN(?oLabel) > 1)
                                }}
                                UNION
                                {{
                                    # Entity2 -> Entity1 (양방향 부분 일치)
                                    ?s ?p ?o .
                                    ?s rdfs:label ?sLabel .
                                    ?o rdfs:label ?oLabel .
                                    FILTER(CONTAINS(LCASE(?sLabel), LCASE("{safe_entity2_name}")) || CONTAINS(LCASE("{safe_entity2_name}"), LCASE(?sLabel)))
                                    FILTER(CONTAINS(LCASE(?oLabel), LCASE("{safe_entity1_name}")) || CONTAINS(LCASE("{safe_entity1_name}"), LCASE(?oLabel)))
                                    FILTER(STRLEN(?sLabel) > 1)
                                    FILTER(STRLEN(?oLabel) > 1)
                                }}
                                # Reification 메타데이터 제외
                                FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>)
                                FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#subject>)
                                FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate>)
                                FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#object>)
                                FILTER(?p != <http://www.w3.org/2000/01/rdf-schema#label>)
                            }}
                            """
                            try:
                                log_trace(f"[Fuseki] Pattern 2 Fast Path SPARQL:\n{direct_triple_query}")
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

                                        # [FIX] Label이 없을 경우 URI에서 추출 (KeyError 방지)
                                        s_label = b.get("sLabel", {}).get("value") or (b["s"]["value"].split("/")[-1].split("#")[-1])
                                        o_label = b.get("oLabel", {}).get("value") or (b["o"]["value"].split("/")[-1].split("#")[-1])

                                        found_triples.append({
                                            "subject": s_label,
                                            "predicate": short_p,
                                            "object": o_label
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

                # [RELEVANCE CHECK]
                # Fast Path가 무차별적으로 데이터를 가져오는 것을 방지
                if skip_llm_generation and found_triples:
                    # resolved_uris: List[Tuple[str, str]] -> (name, uri)
                    known_entity_names = [name for name, _ in resolved_uris] if resolved_uris else []
                    relation_keywords = self._extract_relevance_keywords(query_text, known_entity_names)
                    log_trace(f"[Fuseki] Relevance Check Keywords: {relation_keywords}")

                    is_relevant = self._check_triples_relevance(relation_keywords, found_triples)
                    if not is_relevant:
                        log_trace(f"[Fuseki] ⚠️ Fast Path result seems irrelevant to keywords {relation_keywords}. Formatting Fallback to LLM.")
                        skip_llm_generation = False
                        found_triples = [] # Reset to avoid noise
                        found_uris = set()

                # LLM 호출 (Fast Path로 이미 답을 찾은 경우 건너뜀) — QueryGenerationLoop로 감싸서
                # 생성 실패/0건 시 최대 2회까지 에러 되먹임 재시도한다.
                loop_result: Optional[Dict[str, Any]] = None
                emb_service = kwargs.get("embedding_service", default_embedding_service)
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
            "trace_logs": trace_logs
        }

