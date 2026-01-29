
import asyncio
import time
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

# Load .env explicitly
load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    # Try typical path
    load_dotenv("../.env")
    api_key = os.getenv("OPENAI_API_KEY")

print(f"API Key Loaded: {'Yes' if api_key else 'No'} (Start: {api_key[:5] if api_key else 'None'}...)")

async def test_speed():
    client = AsyncOpenAI(api_key=api_key)
    
    text_sample = "오징어 게임은 456억 원의 상금이 걸린 의문의 서바이벌에 참가한 사람들이 최후의 승자가 되기 위해 목숨을 걸고 극한의 게임에 도전하는 이야기를 담은 넷플릭스 시리즈이다."
    
    # Doc2Graph Prompt
    system_prompt = "You are an entity extractor."
    user_prompt = (
        "다음 텍스트에서 주요 명사와 복합 명사를 추출해서 각 명사를 한 줄에 하나씩 출력해줘.\n"
        "출력 포맷(JSON): { \"entities\": [\"명사1\", \"명사2\"] }\n\n"
        f"텍스트:\n{text_sample}"
    )

    print("\n[Test] Sending request to OpenAI (gpt-4o-mini)...")
    start_time = time.time()
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"[Success] Duration: {duration:.2f} seconds")
        print(f"[Response] {response.choices[0].message.content}")
        
    except Exception as e:
        print(f"[Error] {e}")

if __name__ == "__main__":
    asyncio.run(test_speed())
