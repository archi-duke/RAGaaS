import os
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
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

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
    ) -> str:
        """Build the user message following the Vibe Coding Input Contract."""
        
        # Format input according to the contract
        user_content = f"""Input:
- question: {question}
- schema: {self._format_schema_info(schema_info) if schema_info else "(None provided - use general knowledge)"}
- entity_index: {self._format_entity_index(entities or [])}
- property_index: (Infer from schema or use general knowledge)
- prefixes:
{self._format_prefixes()}
"""
        
        if context:
            user_content += f"\n[Additional Context]\n{context}"
        
        return user_content

    def generate(
        self,
        question: str,
        context: Optional[str] = None,
        mode: str = "ontology",
        inverse_relation: str = "auto",
        custom_prompt: Optional[str] = None,
        schema_info: Optional[Dict] = None,
        system_prompt_override: Optional[str] = None,
        entities: Optional[List[str]] = None,  # NEW: Pass known entities
    ) -> Dict:
        """Convert natural language question to SPARQL using Vibe Coding pipeline.
        
        Args:
            question: The natural language question to convert.
            context: Optional additional context (e.g., entity names found).
            mode: Query mode ("ontology" or other).
            inverse_relation: Inverse relation handling ("auto", "always", "none").
            custom_prompt: User-provided prompt override.
            schema_info: Promoted ontology schema (classes, relations).
            system_prompt_override: Complete system prompt override.
            entities: List of known entity names/labels for entity_index.
        
        Returns:
            Dict containing at minimum:
                - sparql: The generated SPARQL query (or None on error).
            And optionally (Vibe Coding output):
                - intent: Detected intent (e.g., RELATION_CHAIN).
                - slots: Extracted slots.
                - template_id: Selected template.
                - mappings: Entity/property mappings.
                - validation: Syntax/schema validation notes.
        """
        from pathlib import Path
        
        system_prompt = ""
        
        # Define prompt file paths
        vibe_prompt_path = Path("data/prompts/sparql_vibe_prompt.txt")
        ontology_prompt_path = Path("data/prompts/sparql_ontology_prompt.txt")
        legacy_prompt_path = Path("data/prompts/sparql_generation_prompt.txt")

        # Prompt selection order:
        # 1. System Prompt Override (from DB - highest priority for production)
        if system_prompt_override:
            system_prompt = system_prompt_override
            print("[SPARQLGenerator] Using system prompt override (from DB)")
        # 2. Custom Prompt (playground individual input)
        elif custom_prompt:
            system_prompt = custom_prompt
            print("[SPARQLGenerator] Using custom prompt")
        # 3. Vibe Prompt FROM FILE (development/fallback)
        elif vibe_prompt_path.exists():
            system_prompt = vibe_prompt_path.read_text(encoding="utf-8")
            print("[SPARQLGenerator] Using Vibe Coding prompt (from file)")
        # 4. Ontology-specific prompt file (if schema_info is provided)
        elif schema_info and ontology_prompt_path.exists():
            system_prompt = ontology_prompt_path.read_text(encoding="utf-8")
            print("[SPARQLGenerator] Using ontology-specific prompt (from file)")
        # 5. Legacy Prompt File
        elif legacy_prompt_path.exists():
            system_prompt = legacy_prompt_path.read_text(encoding="utf-8")
            print("[SPARQLGenerator] Using legacy prompt (from file)")
        # 6. Fallback Default
        else:
            system_prompt = self.DEFAULT_SYSTEM_PROMPT
            print("[SPARQLGenerator] Using default fallback prompt")
        
        # Inject Schema Info if available and NOT using Vibe prompt
        # (Vibe prompt expects schema in user message, not system prompt)
        if schema_info and not system_prompt_override and not Path("data/prompts/sparql_vibe_prompt.txt").exists():
            system_prompt += self._format_schema_info(schema_info)
        
        # Handle inverse relation instructions
        if inverse_relation == "auto" or inverse_relation == "always":
            system_prompt += "\n\n[Additional Instructions]\n- When searching for relationships, actively use Property Path `|` and inverse `^` operators to solve directionality issues (e.g., `rel:teacher_of|^rel:student_of`)."
        elif inverse_relation == "none":
            system_prompt += "\n\n[Additional Instructions]\n- Use ONLY direct relations. Do NOT use inverse `^` operator."

        # Add Custom Prompt (User Override)
        if custom_prompt:
            system_prompt += f"\n\n[USER CUSTOM INSTRUCTIONS (PRIORITY OVERRIDE)]\n{custom_prompt}\n"

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
                timeout=60,
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
