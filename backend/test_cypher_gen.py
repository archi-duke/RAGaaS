
import os
import json
from app.services.retrieval.cypher_generator import CypherGenerator

# Set API Key if needed, or assume it's in env
os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "")

generator = CypherGenerator()
question = "성기훈과 조상우는 무슨 관계이지?"
context = "관련 엔티티 후보: 성기훈, 조상우"
kb_id = "test_kb_id"

result = generator.generate(question, context=context)

print(f"Question: {question}")
print(f"Thought: {result.get('thought')}")
print(f"Cypher:\n{result.get('cypher')}")
