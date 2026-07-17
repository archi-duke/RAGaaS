import json
import requests
from typing import Optional, Dict, List

class SPARQLGenerator:
    """LLM-based generator that converts natural language questions into SPARQL queries.
    
    Implements the Vibe Coding pipeline:
    Intent + Slots Extraction → Template Selection → Entity/Property Mapping → SPARQL Generation
    """

    # Standard Prefixes used in RAGaaS
    STANDARD_PREFIXES = {
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "owl": "http://www.w3.org/2002/07/owl#",
        "xsd": "http://www.w3.org/2001/XMLSchema#",
        "inst": "http://rag.local/inst/",
        "rel": "http://rag.local/rel/",
        "prop": "http://rag.local/prop/",
        "class": "http://rag.local/class/",
    }

    # Legacy fallback prompt (only used if all file-based prompts fail)
    DEFAULT_SYSTEM_PROMPT = """You are an expert in SPARQL and Knowledge Graphs.
Based on the provided Ontology Schema and rules, convert the natural language question into an executable SPARQL 1.1 query.

[Ontology Schema]
1. Namespaces (Prefixes):
   - rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
   - rdfs: <http://www.w3.org/2000/01/rdf-schema#>
   - owl: <http://www.w3.org/2002/07/owl#>
   - xsd: <http://www.w3.org/2001/XMLSchema#>
   - inst: <http://rag.local/inst/>  (Instance)
   - rel: <http://rag.local/rel/>    (Relation/Predicate)
   - prop: <http://rag.local/prop/>  (Property)
   - class: <http://rag.local/class/> (Class)

2. Key Structures and Rules:
   - Every entity has a URI (e.g., inst:Seong_Gi_hun).
   - Entity names (Labels) are stored in the `rdfs:label` property (as string literals).
   - Example: `?s rdfs:label "Seong Gi-hun"`
   - **Relation Directionality Matters**: 
     - `rel:student_of`: `[Student] rel:student_of [Teacher]` -> Student is Subject, Teacher is Object.
     - `rel:teacher_of`: `[Teacher] rel:teacher_of [Student]` -> Teacher is Subject, Student is Object.
   - **When finding a teacher**: Search for `?student rel:student_of ?teacher` or `?teacher rel:teacher_of ?student`.

3. Relationship Search:
   - Identify the intent of the question and infer the appropriate `rel:relation_name`.
   - If direction-agnostic search is needed, use Property Paths (`|` or `^`).
     - Example: You can use `(rel:student_of|^rel:teacher_of)` to find a teacher.

[Writing Principles]
1. **Include PREFIXES**: Define all the above Namespaces at the beginning of the query.
2. **Entity Matching (Critical)**:
   - Use `rdfs:label` to find by name, preferably using `FILTER(STR(?label) = "Name")`.
3. **Return Results**:
   - Use `DISTINCT` whenever possible.

[Example]
Question: "Who is Seong Gi-hun's teacher?"
SPARQL:
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rel: <http://rag.local/rel/>
SELECT DISTINCT ?teacherLabel WHERE {
  ?s rdfs:label ?sLabel .
  FILTER(STR(?sLabel) = "Seong Gi-hun") .
  ?s (rel:student_of|^rel:teacher_of) ?teacher .
  ?teacher rdfs:label ?teacherLabel .
}

You MUST respond in JSON format:
{
  "thought": "logical reasoning process",
  "sparql": "generated SPARQL query"
}
"""
    
    SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT  # For UI compat


    def __init__(
        self,
        llm_endpoint: Optional[str] = None,
        llm_model: str = "gpt-4o",
        api_key: Optional[str] = None,
    ):
        self.llm_endpoint = llm_endpoint or "https://api.openai.com/v1/chat/completions"
        self.llm_model = llm_model
        self.api_key = api_key
        if not self.api_key:
            raise ValueError("SPARQLGenerator model API key is not configured.")

    def _format_prefixes(self) -> str:
        """Format standard prefixes as a string for inclusion in prompts."""
        lines = []
        for prefix, uri in self.STANDARD_PREFIXES.items():
            lines.append(f"  - {prefix}: <{uri}>")
        return "\n".join(lines)

    def _format_schema_info(self, schema_info: Dict) -> str:
        """Format schema_info into a readable string for the LLM."""
        if not schema_info:
            return ""
        
        schema_text = "\n\n[Active Ontology Schema]\n"
        schema_text += "This Knowledge Base follows a specific ontology. Use these Classes and Relations PREFERENTIALLY:\n"
        
        classes = schema_info.get('classes', {})
        if classes:
            schema_text += "\n1. Classes:\n"
            for cls_key, cls_val in classes.items():
                if isinstance(cls_val, dict):
                    label = cls_val.get('label', cls_key)
                    desc = cls_val.get('description', '')
                    schema_text += f"   - {label}" + (f": {desc}" if desc else "") + "\n"
                else:
                    schema_text += f"   - {cls_key}\n"

        relations = schema_info.get('relations', [])
        if relations:
            schema_text += "\n2. Relations:\n"
            for rel in relations:
                if isinstance(rel, dict):
                    label = rel.get('label', rel.get('uri', 'Unknown'))
                    schema_text += f"   - {label}\n"
                elif isinstance(rel, str):
                    schema_text += f"   - {rel}\n"
        
        return schema_text

    def _format_entity_index(self, entities: List[str]) -> str:
        """Format entity candidates as entity_index for the LLM."""
        if not entities:
            return "[]"
        return json.dumps(entities, ensure_ascii=False)

    def _build_user_message(
        self,
        question: str,
        context: Optional[str] = None,
        schema_info: Optional[Dict] = None,
        entities: Optional[List[str]] = None,
        live_schema: Optional[Dict] = None, # [NEW]
        context_predicates: Optional[List[str]] = None, # [NEW] Entity-Centric
        few_shot_examples: Optional[List[Dict]] = None,
    ) -> str:
        """Build the user message following the Vibe Coding Input Contract."""
        
        # Combine static schema and live schema for property_index
        all_predicates = set()
        all_classes = set()
        
        if schema_info:
            # Extract names from promoted schema
            rels = schema_info.get("relations", [])
            for r in rels:
                if isinstance(r, dict):
                    all_predicates.add(r.get("label", r.get("uri")))
                else: all_predicates.add(str(r))
            
            clses = schema_info.get("classes", {})
            for c_key, c_val in clses.items():
                if isinstance(c_val, dict):
                    all_classes.add(c_val.get("label", c_key))
                else: all_classes.add(str(c_key))
        
        if live_schema:
            for p in live_schema.get("predicates", []): all_predicates.add(p)
            for c in live_schema.get("classes", []): all_classes.add(c)

        # [NEW] Entity-Centric Predicates 우선 사용
        # context_predicates가 제공되면 property_index를 이것으로 대체
        if context_predicates:
            all_predicates = set(context_predicates)

        # Format input according to the contract
        user_content = f"""Input:
- question: {question}
- schema: (Classes: {", ".join(list(all_classes)) if all_classes else "(None detected in DB - Avoid rdf:type)"})
- entity_index: {self._format_entity_index(entities or [])}
- property_index: {json.dumps(list(all_predicates), ensure_ascii=False) if all_predicates else "(Infer from general knowledge)"}
- prefixes:
{self._format_prefixes()}
"""
        
        # [NEW] Entity-Centric 힌트 추가
        if context_predicates:
            user_content += f"""
[IMPORTANT - Entity-Centric Context]
The following predicates are CONFIRMED to exist in the database for the entities mentioned in the question:
{json.dumps(context_predicates, ensure_ascii=False, indent=2)}

These predicates were directly extracted from the graph for the entities in the question.
STRONGLY PREFER using these predicates over inventing new ones or relying on general knowledge.
"""
        
        if context:
            user_content += f"\n[Additional Context]\n{context}"

        if few_shot_examples:
            examples_text = "\n\n".join(
                f'질문: {ex.get("question")}\nSPARQL: {ex.get("query_text")}'
                for ex in few_shot_examples
            )
            user_content += f"\n\n[참고 예시 — 이 KB에서 과거에 성공한 질문-쿼리 쌍]\n{examples_text}"

        return user_content

    def _fetch_fuseki_schema(self, kb_id: str) -> Optional[Dict]:
        """Fetch live schema (predicates and classes) from Fuseki for the given KB."""
        if not kb_id:
            return None
            
        try:
            # Import inside method to avoid circular import (fuseki_client might depend on sparql_generator)
            from app.core.fuseki import fuseki_client
            
            schema_info = {
                "predicates": [],
                "classes": []
            }
            
            # 1. Fetch frequent Predicates (Top 50)
            # Filter out system predicates
            # Use UnionGraph to include data in Named Graphs
            pred_query = """
            SELECT DISTINCT ?p (COUNT(?s) as ?count)
            FROM <urn:x-arq:UnionGraph>
            WHERE {
              ?s ?p ?o .
              FILTER (!regex(str(?p), "rdf-syntax-ns#", "i"))
              FILTER (!regex(str(?p), "rag.local/meta", "i"))
              FILTER (!regex(str(?p), "rag.local/stmt", "i"))
            }
            GROUP BY ?p
            ORDER BY DESC(?count)
            LIMIT 200
            """
            
            pred_results = fuseki_client.query_sparql(kb_id, pred_query)
            bindings = pred_results.get("results", {}).get("bindings", [])
            for b in bindings:
                p_val = b["p"]["value"]
                # Convert URI to short form if possible (e.g., rel:uses)
                if "/rel/" in p_val:
                    short_p = "rel:" + p_val.split("/rel/")[-1]
                elif "#" in p_val:
                    short_p = p_val.split("#")[-1]
                else:
                    short_p = p_val
                schema_info["predicates"].append(short_p)
                
            # 2. Fetch Classes (Limit 20)
            class_query = """
            SELECT DISTINCT ?c
            FROM <urn:x-arq:UnionGraph>
            WHERE {
              [] a ?c .
              FILTER (!regex(str(?c), "rdf-syntax-ns#", "i"))
            }
            LIMIT 20
            """
            class_results = fuseki_client.query_sparql(kb_id, class_query)
            c_bindings = class_results.get("results", {}).get("bindings", [])
            for b in c_bindings:
                c_val = b["c"]["value"]
                if "/class/" in c_val:
                    short_c = "class:" + c_val.split("/class/")[-1]
                else:
                    short_c = c_val.split("/")[-1]
                schema_info["classes"].append(short_c)
            
            pred_count = len(schema_info['predicates'])
            class_count = len(schema_info['classes'])
            
            if pred_count == 0 and class_count == 0:
                print(f"[SPARQLGenerator] WARNING: Dynamic Schema fetched but EMPTY for {kb_id}. Predicates: {pred_count}, Classes: {class_count}")
            else:
                print(f"[SPARQLGenerator] Dynamic Schema for {kb_id}: {pred_count} predicates, {class_count} classes")
                
            return schema_info
            
        except Exception as e:
            print(f"[SPARQLGenerator] ERROR fetching dynamic schema: {e}")
            import traceback
            traceback.print_exc()
            return None

    def generate(
        self,
        question: str,
        context: Optional[str] = None,
        mode: str = "ontology",
        inverse_relation: str = "auto",
        custom_prompt: Optional[str] = None, # Kept for backward compatibility but used as Context
        schema_info: Optional[Dict] = None,
        # system_prompt_override: Removed
        entities: Optional[List[str]] = None,
        kb_id: Optional[str] = None,     # [NEW]
        use_dynamic_schema: bool = True,  # Default to True
        context_predicates: Optional[List[str]] = None,  # [NEW] Entity-Centric Schema
        few_shot_examples: Optional[List[Dict]] = None,
    ) -> Dict:
        """Convert natural language question to SPARQL using Vibe Coding pipeline."""
        print(f"[SPARQLGenerator] Generate called. KB: {kb_id}, DynamicSchema: {use_dynamic_schema}", flush=True)
        
        from pathlib import Path
        
        system_prompt = ""
        
        # Define prompt file paths
        vibe_prompt_path = Path("data/prompts/sparql_vibe_prompt.txt")
        
        # [REFAC] Strict Internal Prompt Policy
        # Use ONLY the Vibe Coding prompt file.
        if vibe_prompt_path.exists():
            system_prompt = vibe_prompt_path.read_text(encoding="utf-8")
            print("[SPARQLGenerator] Using Vibe Coding prompt (internal file)", flush=True)
        else:
            # Minimal Fallback if file is missing (Safety Net)
            print("[SPARQLGenerator] WARNING: Vibe prompt file missing! Using minimal fallback.", flush=True)
            system_prompt = """You are a SPARQL Query Generator.
            generate SPARQL 1.1 query for the user question.
            Output JSON only: {"sparql": "..."}
            """

        # [NEW] Dynamic Schema Injection
        live_schema = None
        if use_dynamic_schema and kb_id:
            print(f"[SPARQLGenerator] Attempting to fetch live schema for KB {kb_id}...", flush=True)
            live_schema = self._fetch_fuseki_schema(kb_id)
            if live_schema:
                print(f"[SPARQLGenerator] Fetched live schema for KB {kb_id}", flush=True)

        # Handle inverse relation instructions
        if inverse_relation == "auto" or inverse_relation == "always":
            system_prompt += "\n\n[Additional Instructions]\n- When searching for relationships, actively use Property Path `|` and inverse `^` operators to solve directionality issues (e.g., `rel:teacher_of|^rel:student_of`)."
        elif inverse_relation == "none":
            system_prompt += "\n\n[Additional Instructions]\n- Use ONLY direct relations. Do NOT use inverse `^` operator."
        
        # [CRITICAL] If Simple Mode (no classes), add a note to system prompt too for redundancy
        if live_schema and not live_schema.get("classes"):
            system_prompt += "\n\n[CRITICAL]: No ontology classes found - avoid using rdf:type."

        # Add Custom Prompt (User Context) - Demoted from Override to Append
        if custom_prompt:
             # Just append it as a "Note" to the system prompt purely for context, 
             # OR pass it in user message. Let's append to system prompt as 'User Context' section 
             # but ensuring it doesn't override the Vibe persona.
            system_prompt += f"\n\n[User Context / Specific Request]\n{custom_prompt}\n"
            
        # Build user message
        # Parse entities from context if not explicitly provided
        if entities is None and context:
            # Try to extract entity names from context string
            # Format is usually "Entities: A, B, C"
            if "Entities:" in context:
                entity_str = context.split("Entities:")[-1].strip()
                entities = [e.strip() for e in entity_str.split(",") if e.strip()]
        
        user_content = self._build_user_message(
            question=question,
            context=context,
            schema_info=schema_info,
            entities=entities,
            live_schema=live_schema, # [NEW]
            context_predicates=context_predicates, # [NEW]
            few_shot_examples=few_shot_examples,
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.0,
        }

        try:
            response = requests.post(
                self.llm_endpoint,
                headers=headers,
                json=payload,
                timeout=180,  # 추론(thinking) 모델은 60초를 초과할 수 있음
            )
            response.raise_for_status()
            
            content = response.json()["choices"][0]["message"]["content"]
            
            # Extract JSON from response
            content = content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            result = json.loads(content.strip())
            
            # Log Vibe Coding metadata if available
            if "intent" in result:
                print(f"[SPARQLGenerator] Intent: {result.get('intent')}")
            if "template_id" in result:
                print(f"[SPARQLGenerator] Template: {result.get('template_id')}")
            if "mappings" in result:
                print(f"[SPARQLGenerator] Mappings: {json.dumps(result.get('mappings'), ensure_ascii=False)}")
            
            return result

        except json.JSONDecodeError as e:
            print(f"[SPARQLGenerator] JSON Parse Error: {e}")
            print(f"[SPARQLGenerator] Raw content: {content[:500] if content else 'None'}")
            return {"error": f"JSON parse error: {e}", "sparql": None}
        except Exception as e:
            print(f"[SPARQLGenerator] Error: {e}")
            return {"error": str(e), "sparql": None}
