# RAGaaS의 BM25 키워드 검색 동작 원리

## 개요

RAGaaS 시스템에서 Keyword (BM25) 검색이 어떻게 동작하는지, 특히 한국어 처리를 위한 형태소 분석이 왜 필수적인지 설명합니다.

## BM25 검색 프로세스

### 전체 흐름도

```
1. LLM 키워드 추출 (옵션)
   ↓
   "성기훈의 스승은 누구야?" → "성기훈 스승"

2. Milvus에서 후보 청크 수집
   ↓
   Knowledge Base의 모든 청크 조회 (최대 2,000개)

3. 형태소 분석 ⭐ 핵심!
   ↓
   쿼리: ["성기훈", "스승"]
   청크1: ["성기훈", "오일남", "제자"]
   청크2: ["성기훈", "스승", "님"]
   청크3: ["성기훈", "스승", "오일남"]
   
   → 모두 동일한 토큰 형태로 변환 (조사/어미 제거)

4. BM25 점수 계산
   ↓
   토큰 매칭 기반으로 TF-IDF 점수 계산

5. 최종 청크 선정
   ↓
   상위 top_k개 반환
```

---

## 각 단계별 상세 설명

### 1단계: LLM 키워드 추출 (옵션)

#### 목적
한국어의 복잡한 문법 구조를 단순화하여 검색 정확도를 향상시킵니다.

#### 문제점
```
원본 쿼리: "성기훈의 스승은 누구야?"
```
- 조사: "의", "은"
- 종결어미: "누구야"
- 불필요한 기능어들이 검색 정확도를 떨어뜨림

#### 해결책
```
LLM 추출 후: "성기훈 스승"
```
- 핵심 명사만 남김
- BM25가 집중해야 할 키워드를 명확히 함
- 노이즈 제거로 검색 정확도 향상

#### 구현
```python
async def extract_keywords_with_llm(self, query: str) -> str:
    prompt = f"""
    Extract the core keywords from the following Korean query, 
    removing particles (Josa) and functional words.
    Return ONLY the keywords separated by spaces.
    
    Query: {query}
    Keywords:
    """
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    response = await client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=50
    )
    return response.choices[0].message.content.strip()
```

#### 실제 효과
- 형태소 분석기(Kiwi)가 놓칠 수 있는 복합 표현 처리
- 구어체 쿼리("누구야", "뭐야")를 표준 키워드로 정규화
- 불필요한 토큰으로 인한 점수 희석 방지

---

### 2단계: 후보 문서 수집

#### 목적
BM25 알고리즘에 필요한 전체 문서 집합(Corpus) 통계 정보를 확보합니다.

#### BM25 알고리즘의 핵심 요소

1. **TF (Term Frequency)**: 특정 단어가 문서에 얼마나 자주 등장하는가?
2. **IDF (Inverse Document Frequency)**: 특정 단어가 전체 문서 중 몇 개에 등장하는가?
   - 희귀한 단어일수록 높은 가중치
   - 흔한 단어("이", "그")는 낮은 가중치

#### 왜 전체 문서가 필요한가?

```python
# IDF 계산 공식 (단순화)
IDF(단어) = log(전체_문서_수 / 단어가_포함된_문서_수)
```

**예시:**
- "성기훈"이 1,000개 문서 중 5개에만 등장 → 높은 IDF (중요한 키워드)
- "입니다"가 1,000개 문서 중 900개에 등장 → 낮은 IDF (일반적인 단어)

#### 구현
```python
# Milvus에서 모든 청크 조회
results = collection.query(
    expr="id >= 0",  # 모든 문서
    output_fields=["content", "doc_id", "chunk_id"],
    limit=2000       # 최대 2,000개
)
```

#### 현재 구현의 제약사항
- Milvus는 **벡터 검색에 최적화**된 DB
- **역색인(Inverted Index)이 없음** → 전체 문서를 가져와야 함
- 대규모 시스템에서는 Elasticsearch/Solr 사용 권장

---

### 3단계: 형태소 분석 ⭐

#### 핵심 질문: 왜 형태소 분석이 필요한가?

**문제 상황:**
```python
# 1번에서 LLM이 추출한 키워드
query_keywords = "성기훈 스승"

# 2번에서 가져온 후보 청크 내용
chunk_1 = "성기훈은 오일남의 제자였다."
chunk_2 = "성기훈이 스승님께 배웠다."
chunk_3 = "성기훈의 스승은 오일남이다."
```

**이 상태로 BM25를 돌리면?**
- "성기훈" vs "성기훈은" vs "성기훈이" vs "성기훈의" → **모두 다른 단어로 인식!**
- "스승" vs "스승님" vs "제자" → **관련 있지만 매칭 안 됨!**

#### 형태소 분석의 역할

**쿼리 토큰화:**
```python
tokenized_query = korean_tokenize("성기훈 스승", mode='strict')
# 결과: ["성기훈", "스승"]
```

**청크 토큰화:**
```python
# chunk_1: "성기훈은 오일남의 제자였다"
tokens_1 = ["성기훈", "오일남", "제자"]  # "은", "의", "였다" 제거

# chunk_2: "성기훈이 스승님께 배웠다"
tokens_2 = ["성기훈", "스승", "님"]  # "이", "께", "배우" 제거

# chunk_3: "성기훈의 스승은 오일남이다"
tokens_3 = ["성기훈", "스승", "오일남"]  # "의", "은", "이다" 제거
```

#### 구현: Kiwi 형태소 분석기

```python
def korean_tokenize(
    text: str,
    mode: Literal['strict', 'extended'] = 'strict',
    include_original_words: bool = False,
    min_length: int = 1
) -> List[str]:
    """
    Tokenize Korean text using Kiwi morphological analyzer.
    
    Args:
        text: Input text to tokenize
        mode: Tokenization mode
            - 'strict': Nouns only (NNG, NNP, NR, NP, SL)
            - 'extended': Nouns + Verbs + Adjectives
        include_original_words: If True, also include original words
        min_length: Minimum token length to include
    """
    kiwi = _get_kiwi()
    tokens = []
    result = kiwi.analyze(text)
    
    # BM25는 strict mode 사용 (명사만 추출)
    if mode == 'strict':
        allowed_tags = {'NNG', 'NNP', 'NR', 'NP', 'SL'}
    else:  # 'extended'
        allowed_tags = {'NNG', 'NNP', 'NR', 'NP', 'SL', 'VV', 'VA'}
    
    best_analysis = result[0][0]
    for token in best_analysis:
        if token.tag in allowed_tags:
            if len(token.form) >= min_length:
                tokens.append(token.form)
    
    return tokens
```

#### 실제 코드 적용

```python
# 쿼리와 모든 청크를 동일한 방식으로 토큰화
tokenized_corpus = [
    korean_tokenize(hit.get("content", ""), mode='strict') 
    for hit in results  # 2,000개 청크 각각
]

tokenized_query = korean_tokenize(search_query, mode='strict')
```

#### 왜 1번 LLM 추출만으로는 부족한가?

| 단계 | 대상 | 목적 |
|------|------|------|
| **1번 LLM 키워드 추출** | 쿼리만 | 쿼리 정제 (옵션) |
| **3번 형태소 분석** | 쿼리 + 모든 청크 | **필수!** 동일한 토큰 공간으로 변환 |

**형태소 분석의 역할:**
- **쿼리 + 모든 청크 내용**을 동일한 기준으로 정규화
- 조사 제거: "성기훈은/이/의/께서" → "성기훈"
- 어미 제거: "배웠다/배우다" → "배우"
- 명사 추출: "스승님" → "스승", "님"

---

### 4단계: BM25 점수 계산

#### BM25Okapi 알고리즘 적용

```python
from rank_bm25 import BM25Okapi

# BM25 모델 생성
bm25 = BM25Okapi(tokenized_corpus)

# 각 문서의 점수 계산
doc_scores = bm25.get_scores(tokenized_query)
```

#### 점수 계산 예시

```python
# Query: ["성기훈", "스승"]

# chunk_1: ["성기훈", "오일남", "제자"]
# 매칭: "성기훈" (1개) → 낮은 점수

# chunk_2: ["성기훈", "스승", "님"]
# 매칭: "성기훈", "스승" (2개) → 높은 점수

# chunk_3: ["성기훈", "스승", "오일남"]
# 매칭: "성기훈", "스승" (2개) → 높은 점수
```

#### BM25 점수 특성
- 0-1 범위가 아닌 **양수 실수값**
- 토큰 매칭 개수와 희귀도(IDF)를 종합적으로 고려
- 점수가 0 이하인 문서는 관련성 없음으로 판단

---

### 5단계: 최종 청크 선정

#### 결과 필터링 및 정렬

```python
retrieved = []
for i, score in enumerate(doc_scores):
    # BM25 점수가 0 이하인 문서 제외
    if score <= 0:
        continue
        
    hit = results[i]
    retrieved.append({
        "chunk_id": hit.get("chunk_id"),
        "content": hit.get("content"),
        "score": float(score),
        "metadata": {"doc_id": hit.get("doc_id")}
    })

# 점수 기준 내림차순 정렬
retrieved.sort(key=lambda x: x["score"], reverse=True)

# 상위 top_k개 반환
final_res = retrieved[:top_k]
```

#### 메타데이터 첨부

```python
# UI에서 어떤 키워드로 검색되었는지 표시
for result in final_res:
    result["metadata"]["extracted_keywords"] = tokenized_query
```

---

## 핵심 정리

### 형태소 분석이 필수인 이유

**한국어는 교착어 특성을 가지고 있습니다:**
- "성기훈" + "은/이/의/께서/에게/..." → 수십 가지 변형
- 형태소 분석 없이는 **동일한 단어를 다른 단어로 인식**

**형태소 분석의 효과:**
```
"성기훈은" = "성기훈이" = "성기훈의" = "성기훈"
```
→ 쿼리와 문서를 **동일한 토큰 공간**에서 비교 가능

### BM25 검색의 장단점

#### ✅ 장점
- **정확한 키워드 매칭** (형태소 분석 기반)
- 한국어 조사 제거로 검색 정확도 향상
- **어휘적 일치** 중심 (벡터 검색과 상호 보완적)
- 희귀 키워드에 높은 가중치 부여 (IDF)

#### ⚠️ 제약사항
- 현재 구현은 **전체 문서를 메모리에 로드** (최대 2,000개)
- 대규모 데이터셋에는 Elasticsearch/Solr 같은 역색인 시스템 권장
- 동의어나 의미적 유사성은 포착하지 못함 (순수 키워드 매칭)

---

## 실제 코드 흐름

```python
# keyword.py - KeywordRetrievalStrategy.search()

# 1. LLM 키워드 추출 (옵션)
if use_llm_extraction:
    search_query = await self.extract_keywords_with_llm(query)

# 2. Milvus에서 후보 청크 수집
collection = create_collection(kb_id)
results = collection.query(
    expr="id >= 0",
    output_fields=["content", "doc_id", "chunk_id"],
    limit=2000
)

# 3. 형태소 분석
tokenized_corpus = [
    korean_tokenize(hit.get("content", ""), mode='strict') 
    for hit in results
]
tokenized_query = korean_tokenize(search_query, mode='strict')

# 4. BM25 점수 계산
bm25 = BM25Okapi(tokenized_corpus)
doc_scores = bm25.get_scores(tokenized_query)

# 5. 최종 청크 선정
retrieved = []
for i, score in enumerate(doc_scores):
    if score <= 0:
        continue
    retrieved.append({
        "chunk_id": results[i].get("chunk_id"),
        "content": results[i].get("content"),
        "score": float(score),
        "metadata": {"doc_id": results[i].get("doc_id")}
    })

retrieved.sort(key=lambda x: x["score"], reverse=True)
return retrieved[:top_k]
```

---

## 참고 자료

- **BM25 알고리즘**: [Wikipedia - Okapi BM25](https://en.wikipedia.org/wiki/Okapi_BM25)
- **Kiwi 형태소 분석기**: [kiwipiepy GitHub](https://github.com/bab2min/kiwipiepy)
- **rank-bm25 라이브러리**: [PyPI - rank-bm25](https://pypi.org/project/rank-bm25/)

---

## 결론

RAGaaS의 BM25 키워드 검색은 **형태소 분석**을 통해 한국어의 교착어 특성을 극복하고, 쿼리와 문서를 동일한 토큰 공간에서 비교함으로써 정확한 키워드 매칭을 실현합니다. 

이는 벡터 검색(의미적 유사성)과 상호 보완적으로 작동하여, Hybrid 검색 모드에서 더욱 강력한 검색 성능을 제공합니다.
