"""
Subject Restoration Preprocessing Module

Resolves omitted subjects in Korean text using LLM.
Example: "이며 Duke의 제자이다" → "오일남은 Duke의 제자이다"
"""
import os
from openai import OpenAI

# Initialize OpenAI client
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

SYSTEM_PROMPT = """당신은 한국어 텍스트 전처리 전문가입니다.
주어진 텍스트에서 **생략된 주어를 복원**하는 작업을 수행합니다.

규칙:
1. "이며", "그리고", "또한" 등으로 연결된 문장에서 생략된 주어를 앞 문장에서 찾아 명시적으로 추가합니다.
2. 인물 설명 문단에서 주어(인물 이름)가 생략된 경우, 해당 인물 이름을 주어로 추가합니다.
3. 원문의 의미는 절대 변경하지 마세요.
4. **절대 대화하듯이작성하지 마세요.** (예: "수정된 텍스트입니다" 등의 말 금지)
5. 변경할 내용이 없다면 **입력된 텍스트를 그대로 출력**하세요.
6. 오직 결과 텍스트만 출력하세요.

예시:
입력: "오영수 - 001번 오일남 역: 뇌종양을 앓고 있는 노인. '장풍'의 고수 이며 Duke의 제자 이다."
출력: "오영수 - 001번 오일남 역: 오일남은 뇌종양을 앓고 있는 노인이다. 오일남은 '장풍'의 고수 이며 오일남은 Duke의 제자 이다."
"""


async def restore_subjects(text: str, model: str = "gpt-4o-mini") -> str:
    """
    Restore omitted subjects in Korean text using LLM.
    
    Args:
        text: Input text with potentially omitted subjects.
        model: OpenAI model to use.
        
    Returns:
        Text with restored subjects.
    """
    try:
        print(f"[SubjectRestoration] Processing {len(text)} chars...")
        
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            temperature=0.1,
            max_tokens=len(text) * 2  # Allow some expansion
        )
        
        restored_text = response.choices[0].message.content.strip()
        reduced_text = restored_text[:20].lower()
        if any(x in reduced_text for x in ["죄송", "sorry", "i cannot", "unable to", "제공된 텍스트", "cannot fulfill"]):
            print(f"[SubjectRestoration] ⚠️ Startup detected refusal/chat pattern. Reverting to original text.")
            return text

        print(f"[SubjectRestoration] Restored to {len(restored_text)} chars")
        
        return restored_text
        
    except Exception as e:
        print(f"[SubjectRestoration] ⚠️ Error: {e}. Returning original text.")
        return text
