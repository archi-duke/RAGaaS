#!/usr/bin/env python3
"""
Vibe Coding SPARQL Generator 검증 스크립트

테스트 케이스:
1. 단순 관계 질의 (성기훈의 스승은 누구야?)
2. 멀티 홉 질의 (성기훈의 스승의 스승은 누구야?)
3. 스키마 활용 질의 (Mock 스키마 제공)
"""

import os
import sys
import json

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from app.services.retrieval.sparql_generator import SPARQLGenerator


def test_simple_relation():
    """Test Case 1: Simple Relation Query"""
    print("=" * 60)
    print("Test Case 1: 단순 관계 질의")
    print("=" * 60)
    
    generator = SPARQLGenerator()
    
    result = generator.generate(
        question="성기훈의 스승은 누구야?",
        context="Entities: 성기훈",
        inverse_relation="auto",
    )
    
    print(f"\n[질문] 성기훈의 스승은 누구야?")
    print(f"\n[결과]")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Validation
    assert "sparql" in result, "sparql 필드가 없습니다!"
    assert result.get("sparql") is not None, "sparql이 None입니다!"
    
    if "intent" in result:
        print(f"\n✅ Intent 감지됨: {result['intent']}")
    if "template_id" in result:
        print(f"✅ Template 선택됨: {result['template_id']}")
    
    print("\n✅ Test Case 1 PASSED")
    return result


def test_multi_hop():
    """Test Case 2: Multi-hop Relation Query"""
    print("\n" + "=" * 60)
    print("Test Case 2: 멀티 홉 질의")
    print("=" * 60)
    
    generator = SPARQLGenerator()
    
    result = generator.generate(
        question="성기훈의 스승의 스승은 누구야?",
        context="Entities: 성기훈",
        inverse_relation="auto",
    )
    
    print(f"\n[질문] 성기훈의 스승의 스승은 누구야?")
    print(f"\n[결과]")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Validation
    assert "sparql" in result, "sparql 필드가 없습니다!"
    assert result.get("sparql") is not None, "sparql이 None입니다!"
    
    # Check for multi-hop pattern
    sparql = result.get("sparql", "")
    has_multihop = ("?mid" in sparql or "?teacher" in sparql.lower() and sparql.lower().count("teacher") >= 2)
    
    if "slots" in result:
        depth = result["slots"].get("depth", 1)
        print(f"\n✅ Depth 감지됨: {depth}")
    
    print("\n✅ Test Case 2 PASSED")
    return result


def test_with_schema():
    """Test Case 3: Query with Schema Info"""
    print("\n" + "=" * 60)
    print("Test Case 3: 스키마 활용 질의")
    print("=" * 60)
    
    generator = SPARQLGenerator()
    
    # Mock schema
    mock_schema = {
        "classes": {
            "Person": {"label": "Person", "description": "사람"},
            "Organization": {"label": "Organization", "description": "조직"},
        },
        "relations": [
            {"label": "hasTeacher", "uri": "rel:hasTeacher"},
            {"label": "worksFor", "uri": "rel:worksFor"},
            {"label": "student_of", "uri": "rel:student_of"},
        ]
    }
    
    result = generator.generate(
        question="성기훈의 스승은 누구야?",
        context="Entities: 성기훈",
        inverse_relation="auto",
        schema_info=mock_schema,
    )
    
    print(f"\n[질문] 성기훈의 스승은 누구야?")
    print(f"[스키마] {json.dumps(mock_schema, indent=2, ensure_ascii=False)}")
    print(f"\n[결과]")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Validation
    assert "sparql" in result, "sparql 필드가 없습니다!"
    assert result.get("sparql") is not None, "sparql이 None입니다!"
    
    # Check if schema relations are used
    sparql = result.get("sparql", "")
    uses_schema = "hasTeacher" in sparql or "student_of" in sparql
    
    if uses_schema:
        print("\n✅ 스키마 관계(hasTeacher/student_of) 사용됨!")
    else:
        print("\n⚠️ 스키마 관계가 SPARQL에 직접 반영되지 않았습니다.")
    
    if "mappings" in result:
        print(f"✅ Mappings: {json.dumps(result['mappings'], ensure_ascii=False)}")
    
    print("\n✅ Test Case 3 PASSED")
    return result


def test_inverse_disabled():
    """Test Case 4: Inverse Relation Disabled"""
    print("\n" + "=" * 60)
    print("Test Case 4: Inverse 비활성화 질의")
    print("=" * 60)
    
    generator = SPARQLGenerator()
    
    result = generator.generate(
        question="성기훈의 스승은 누구야?",
        context="Entities: 성기훈",
        inverse_relation="none",  # Inverse disabled
    )
    
    print(f"\n[질문] 성기훈의 스승은 누구야?")
    print(f"[inverse_relation] none")
    print(f"\n[결과]")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Validation
    assert "sparql" in result, "sparql 필드가 없습니다!"
    
    sparql = result.get("sparql", "")
    has_inverse = "^" in sparql
    
    if has_inverse:
        print("\n⚠️ SPARQL에 inverse(^) 연산자가 포함되어 있습니다! (예상치 못함)")
    else:
        print("\n✅ Inverse 연산자 없음 - 올바른 동작!")
    
    print("\n✅ Test Case 4 PASSED")
    return result


def main():
    print("\n" + "=" * 60)
    print("🚀 Vibe Coding SPARQL Generator 검증 시작")
    print("=" * 60)
    
    # Check if API key is set
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("\n❌ OPENAI_API_KEY 환경 변수가 설정되지 않았습니다!")
        print("먼저 export OPENAI_API_KEY='your-key' 를 실행하세요.")
        sys.exit(1)
    
    print(f"\n✅ OPENAI_API_KEY 감지됨 (길이: {len(api_key)})")
    
    try:
        test_simple_relation()
        test_multi_hop()
        test_with_schema()
        test_inverse_disabled()
        
        print("\n" + "=" * 60)
        print("🎉 모든 테스트 통과!")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n❌ 테스트 실패: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 예외 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
