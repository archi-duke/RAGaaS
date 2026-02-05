import os
import json
import requests
from typing import Optional, Dict

class CypherGenerator:
    """LLM-based generator that converts natural language questions into Neo4j Cypher queries"""

    DEFAULT_SYSTEM_PROMPT = """You are an expert in Neo4j Graph Databases.
Generate the optimal Cypher query based on the node labels, properties, and relationship structures of the provided knowledge graph.

[Knowledge Graph Schema Features]
1. Node Labels:
   - :Entity : Knowledge Graph entities (People, Concepts, Objects, etc.)
   - The graph only contains entities and relationships. (Chunk information is managed by a separate system.)
2. Node Properties (:Entity):
   - name : Name of the entity (e.g., "Seong Gi-hun", "Oh Il-nam", "Duke")
   - kb_id : Knowledge Base ID
3. Relationships:
   - Relationship types are often in English or Korean. Wrap them in backticks (`) if they contain special characters or are non-alphanumeric. (e.g., -[:`Teacher`]-)
   - Relationships represent semantic connections between entities.

[Query Writing Principles]
1. Entity Search: Match entities mentioned in the question using the `name` property.
   (e.g., `MATCH (n:Entity {name: "Seong Gi-hun"})`)
2. Flexible Matching: Use `CONTAINS` if the exact name is unknown.
   (e.g., `MATCH (n:Entity) WHERE n.name CONTAINS "Gi-hun"`)
3. Consider Relationship Direction: Since relationship directions may be inconsistent, search without specific direction by default (`(n)-[:`RELATION`]-(m)`). For clear logical sequences (e.g., "Teacher's teacher"), you may consider directional patterns (`(n)<-[:`STUDENT`]-(m)`).
4. Multi-hop Connections: For multi-hop questions, add conditions to ensure the start and end nodes are distinct.
   (e.g., `MATCH (n:Entity {name: "Seong Gi-hun"})-[:`STUDENT`|`TEACHER`]-(m)-[:`STUDENT`|`TEACHER`]-(o) WHERE n <> o RETURN o.name`)
5. Result Format: Use `RETURN` and ensure the output includes **both nodes and relationships** to understand the graph structure.
   (e.g., `RETURN n, r, m`)
6. Always include `kb_id: $kb_id` matching or `n.kb_id = $kb_id` in all searches.
   (e.g., `MATCH (n:Entity {name: "Seong Gi-hun", kb_id: $kb_id})`)
7. Refine Results: Use `DISTINCT` or `collect` to remove duplicates.

Respond ONLY in the following JSON format:
```json
{
  "thought": "The logical process of analyzing the question. Mention if you considered both independent entities and property values.",
  "cypher": "The generated Cypher query. Use patterns for matching names and checking property values (CONTAINS) proactively.",
  "entities": ["List of extracted entities"],
  "relations": ["List of extracted relations"]
}
```

[Special Instructions: Semantic Expansion]
1. **Expand Keyword Search**: Core keywords from the question (e.g., 'skill', 'use') might be hidden not just in labels, but also in **property values** (`description`, `comment`, `features`, etc.) or **associated relationships** (`inventor`, `developer`, etc.).
2. **Use OR Conditions**: Don't rely on a single property. Connect all possible candidates with `OR` to broaden the search scope.
   - e.g., `MATCH (n) WHERE n.features CONTAINS 'Skill' OR n.comment CONTAINS 'Skill' OR exists { (n)-[:INVENTOR]-(:Entity {name: 'Skill'}) }`
3. **Redefining 'User'**: When looking for an 'user', include relationships that logically imply usage, like 'inventor', 'owner', 'practitioner', etc.
4. **Target Return**: Return the **node itself** that satisfies the condition, not its neighbors (unless requested).
   - Correct: `MATCH (n) WHERE n.features CONTAINS 'Skill' RETURN n`
   - Incorrect: `MATCH (n)-[]-(m) WHERE n.features CONTAINS 'Skill' RETURN m` (Incorrectly returns a neighbor)
4. **Bidirectional Search (Mandatory)**: Natural language directions often disagree with stored directions.
   - **Do NOT use arrows (`->`, `<-`) in relationship searches.** Use only dashes (`-[:RELATION]-`).
   - Correct: `(n)-[:RELATION]-(m)`  (100% success probability)
   - Incorrect: `(n)-[:RELATION]->(m)`  (High failure probability)

[Important Constraints]
1. No Imaginary Relationships: Use only relationship types specified in the schema if [Additional Context] is provided.
2. Flexible Search: If a verb in the question (e.g., 'uses') isn't in the schema, choose the closest meaningful relationship or search without types using `(n)-[r]-(m)`.
3. Language Support: Use the `name` property to match entity names.

[Mandatory Syntax Rules - MUST FOLLOW]
1. **Variable Assignment for All Nodes**: Always assign variables to all nodes in MATCH patterns.
   - ✅ Correct: `MATCH (n:Entity)-[r]-(m:Entity)`
   - ❌ Incorrect: `MATCH (n:Entity)-[r]-(:Entity)`
2. **Define Variables Before Use**: Any variable used in WHERE or RETURN must first be defined in MATCH.
   - ✅ Correct: `MATCH (n)-[r]-(m) WHERE m.name = "Sang-woo" RETURN m`
   - ❌ Incorrect: `MATCH (n)-[r]-(:Entity) WHERE m.name = "Sang-woo"` (m undefined)
3. **Variable Assignment for Relationships**: Define variable `r` to use `type(r)`.
   - ✅ Correct: `MATCH (n)-[r]-(m) RETURN type(r)`
   - ❌ Incorrect: `MATCH (n)-[]-(m) RETURN type(r)` (r undefined)

[Absolute Prohibitions - ERROR if violated]
1. **No Variable-Length Paths (*)**: Never use `-[*1..2]-`, `-[r*]-`, or `-[:xxx*1..2]-`. Use only single-hop patterns.
   - ❌ Prohibited: `MATCH (n)-[*1..2]-(m)`, `MATCH (n)-[r*]-(m)`
   - ✅ Allowed: `MATCH (n)-[r]-(m)` (Single-hop only)
2. **No Generic 'Relationship' Type**: `[:\`Relationship\`]` is not a valid type.
   - ❌ Prohibited: `MATCH (n)-[:\`Relationship\`]-(m)`
   - ✅ Allowed: `MATCH (n)-[r]-(m)` (Search all types)
3. **No relationships() function**: The function `relationships(a, b)` does not exist in Neo4j.
   - ❌ Prohibited: `RETURN type(relationships(n, m))`
   - ✅ Allowed: `RETURN type(r)`

[Finding Relationship Between Two Entities - MUST use this pattern]
For questions like "What is the relationship between A and B?", **MUST** use this exact pattern:
```cypher
MATCH (a:Entity {name: "Seong Gi-hun", kb_id: $kb_id})-[r]-(b:Entity {name: "Cho Sang-woo", kb_id: $kb_id})
RETURN a.name, type(r) AS relationship, b.name
```
In this pattern:
- No variable-length paths (*)
- No relationship type specified (searches all using [r])
- Returns relationship type using type(r)
"""

    def __init__(
        self,
        llm_endpoint: Optional[str] = None,
        llm_model: str = "gpt-4o",
        api_key: Optional[str] = None,
    ):
        self.llm_endpoint = llm_endpoint or "https://api.openai.com/v1/chat/completions"
        self.llm_model = llm_model
        # RAGaaS 환경 변수 설정에 맞게 기본값 수정 가능
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

        if not self.api_key:
            # RAGaaS 실행 환경에서 OPENAI_API_KEY가 없을 경우 대비
            pass

    def generate(self, question: str, context: Optional[str] = None, mode: str = "graph", custom_prompt: Optional[str] = None, inverse_search_mode: str = "auto", kb_id: Optional[str] = None, use_dynamic_schema: bool = False) -> Dict:
        """사용자 질문을 Cypher로 변환"""
        
        print(f"[CypherGenerator] Generate called. KB: {kb_id}, DynamicSchema: {use_dynamic_schema}", flush=True)
        
        # Dynamic Load from File - Use Vibe Prompt as primary
        from pathlib import Path
        vibe_prompt_path = Path("data/prompts/cypher_vibe_prompt.txt")
        fallback_prompt_path = Path("data/prompts/cypher_generation_prompt.txt")
        
        if vibe_prompt_path.exists():
            system_prompt = vibe_prompt_path.read_text(encoding="utf-8")
            print("[CypherGenerator] Using Cypher Vibe Coding prompt (internal file)", flush=True)
        elif fallback_prompt_path.exists():
            system_prompt = fallback_prompt_path.read_text(encoding="utf-8")
            print("[CypherGenerator] WARNING: Using fallback prompt (cypher_generation_prompt.txt)", flush=True)
        else:
            system_prompt = self.DEFAULT_SYSTEM_PROMPT
            print("[CypherGenerator] WARNING: Using hardcoded default prompt", flush=True)

        # Dynamic Schema Injection (for non-promoted KBs)
        if use_dynamic_schema and kb_id:
            print(f"[CypherGenerator] Attempting to fetch live schema for KB {kb_id}...", flush=True)
            schema_info = self._fetch_neo4j_schema(kb_id)
            if schema_info:
                print(f"[CypherGenerator] Fetched live schema for KB {kb_id}: {len(schema_info.get('relationship_types', []))} relationships", flush=True)
                system_prompt += f"""

[현재 데이터베이스 스키마 - 반드시 준수]
사용 가능한 관계 타입(Relationship Types): {schema_info.get('relationship_types', [])}
사용 가능한 노드 라벨(Node Labels): {schema_info.get('node_labels', [])}

**주의**: 위 목록에 없는 관계 타입이나 노드 라벨은 절대 사용하지 마세요. 
질문에 "관계"라는 단어가 있더라도, 위 목록에 "관계"가 없으면 타입을 지정하지 말고 [r]로 모든 관계를 탐색하세요.
"""
        
        # 그래프 검색 모드 특화 지침 (필요 시 보강)
        if mode == "graph":
            graph_instruction = """
[추가 지침]
"""
            if inverse_search_mode in ["auto", "always"]:
                graph_instruction += "- 관계 방향이 데이터 적재 방식에 따라 반대일 수 있으니, 무방향성 검색 `(n)-[:REL]-(m)` 또는 양방향 패턴을 적극 활용하세요.\n"
                graph_instruction += "- **핵심**: 사용자가 묻는 관계(예: '스승')가 DB에는 반대 관계(예: '제자')로 저장될 수 있습니다. 반드시 `|`를 사용하여 두 관계를 함께 검색하세요. (예: `-[:스승|제자]-`)\n"
            else:
                graph_instruction += "- 관계 방향을 엄격히 준수하세요. 역방향 검색은 수행하지 마세요.\n"
                graph_instruction += "- 역관계 추적이 비활성화되었습니다. 사용자가 묻는 관계가 DB에 정확히 저장된 방향대로만 검색하세요. (예: '스승'을 물었다면 `-[:스승]-`만 사용)\n"

            graph_instruction += "- 결과값은 가능한 명확한 이름(name)이나 설명이 포함되도록 하세요.\n"
            
            system_prompt += graph_instruction

        # Add Custom Prompt (User Override)
        if custom_prompt:
             system_prompt += f"\n\n[USER CUSTOM INSTRUCTIONS (PRIORITY OVERRIDE)]\n{custom_prompt}\n"

        user_content = f"사용자 질문: {question}"
        if context:
            user_content += f"\n\n[추가 컨텍스트]\n{context}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # 모델이 gpt-4o가 아니면 gpt-4o-mini로 fallback (RAGaaS 기본값)
        target_model = self.llm_model
        
        payload = {
            "model": target_model,
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
            
            # JSON 파싱
            content = content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            return json.loads(content.strip())

        except Exception as e:
            print(f"[CypherGenerator] Error: {e}")
            return {
                "error": str(e),
                "cypher": None
            }
    
    def _fetch_neo4j_schema(self, kb_id: str) -> Optional[Dict]:
        """Neo4j에서 현재 KB의 관계 타입과 노드 라벨을 조회 (캐싱 적용)"""
        try:
            from app.core.neo4j_client import neo4j_client
            
            # Fetch relationship types
            rel_query = """
            MATCH (n:Entity {kb_id: $kb_id})-[r]-(m:Entity {kb_id: $kb_id})
            RETURN DISTINCT type(r) AS rel_type
            LIMIT 100
            """
            rel_records = neo4j_client.execute_query(rel_query, {"kb_id": kb_id})
            relationship_types = [record["rel_type"] for record in rel_records if record.get("rel_type")]
            
            # Fetch node labels (usually just Entity, but could be more)
            label_query = """
            MATCH (n {kb_id: $kb_id})
            RETURN DISTINCT labels(n) AS node_labels
            LIMIT 50
            """
            label_records = neo4j_client.execute_query(label_query, {"kb_id": kb_id})
            node_labels = set()
            for record in label_records:
                if record.get("node_labels"):
                    node_labels.update(record["node_labels"])
            
            schema_info = {
                "relationship_types": relationship_types,
                "node_labels": list(node_labels)
            }
            
            if not relationship_types and not node_labels:
                print(f"[CypherGenerator] WARNING: Dynamic Schema fetched but EMPTY for KB {kb_id}", flush=True)
            else:
                print(f"[CypherGenerator] Dynamic Schema for KB {kb_id}: {len(relationship_types)} relationships, {len(node_labels)} labels", flush=True)
            
            return schema_info
            
        except Exception as e:
            print(f"[CypherGenerator] ERROR fetching schema: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return None

# 사용 예시
if __name__ == "__main__":
    generator = CypherGenerator()
    q = "성기훈의 스승의 스승은 누구야?"
    result = generator.generate(q)
    print(f"Question: {q}")
    print(f"Thought: {result.get('thought')}")
    print(f"Cypher:\n{result.get('cypher')}")
