import os
import json
import requests
from typing import Optional, Dict

class SPARQLGenerator:
    """LLM-based generator that converts natural language questions into SPARQL queries"""

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
    
    SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT # For UI compat


    def __init__(
        self,
        llm_endpoint: Optional[str] = None,
        llm_model: str = "gpt-4o",
        api_key: Optional[str] = None,
    ):
        self.llm_endpoint = llm_endpoint or "https://api.openai.com/v1/chat/completions"
        self.llm_model = llm_model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    def generate(self, question: str, context: Optional[str] = None, mode: str = "ontology", inverse_relation: str = "auto", custom_prompt: Optional[str] = None, schema_info: Optional[Dict] = None, system_prompt_override: Optional[str] = None) -> Dict:
        """Convert natural language question to SPARQL (Supports custom_prompt)"""
        
        # Dynamic Load from File (Priority: Override > File > Default)
        from pathlib import Path
        
        system_prompt = ""
        
        if system_prompt_override:
            system_prompt = system_prompt_override
        else:
            # Select prompt file based on mode/schema availability
            if schema_info:
                prompt_path = Path("data/prompts/sparql_ontology_prompt.txt")
            else:
                prompt_path = Path("data/prompts/sparql_generation_prompt.txt")
    
            if prompt_path.exists():
                system_prompt = prompt_path.read_text(encoding="utf-8")
            else:
                system_prompt = self.DEFAULT_SYSTEM_PROMPT

        
        # Inject Schema Info if available (Promoted Ontology)
        if schema_info:
            # Construct a readable schema description
            schema_text = "\n\n[Active Ontology Schema]\n"
            schema_text += "This Knowledge Base follows a specific ontology. Use these Classes and Relations PREFERENTIALLY:\n"
            
            classes = schema_info.get('classes', {})
            if classes:
                schema_text += "\n1. Classes:\n"
                for cls_key, cls_val in classes.items():
                    # Support both dict (metadata) and simple formats
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
            
            system_prompt += schema_text

        if inverse_relation == "auto" or inverse_relation == "always":
            system_prompt += "\n[Additional Instructions]\n- When searching for relationships, actively use Property Path `|` and inverse `^` operators to solve directionality issues (e.g., `rel:teacher_of|^rel:student_of`)."

        # Add Custom Prompt (User Override)
        if custom_prompt:
            system_prompt += f"\n\n[USER CUSTOM INSTRUCTIONS (PRIORITY OVERRIDE)]\n{custom_prompt}\n"

        user_content = f"User Question: {question}"
        if context:
            user_content += f"\n\n[Context]\n{context}"

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
            
            # Extract JSON
            content = content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            return json.loads(content.strip())

        except Exception as e:
            print(f"[SPARQLGenerator] Error: {e}")
            return {"error": str(e), "sparql": None}
