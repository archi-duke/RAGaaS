#!/bin/bash

KB_ID="27e0c2de-7eb1-48c2-a526-ac6b3e7223ed"
FUSEKI_DATASET="kb_27e0c2de_7eb1_48c2_a526_ac6b3e7223ed"

echo "🔍 문서 등록 모니터링 시작"
echo "KB ID: $KB_ID"
echo "Press Ctrl+C to stop"
echo ""
echo "========================================"

# 초기 상태 체크
echo "[시작] 초기 상태:"
echo -n "  Fuseki 트리플: "
curl -s -X POST "http://localhost:3030/$FUSEKI_DATASET/query" \
  --data-urlencode "query=SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o }" \
  -H "Accept: application/sparql-results+json" | jq -r '.results.bindings[0].count.value' 2>/dev/null || echo "0"

echo -n "  MongoDB 문서: "
docker exec ragaas-mongo mongosh -u root -p example --quiet --eval "
db.getSiblingDB('ragaas').documents.countDocuments({knowledge_base_id: '$KB_ID'})
" 2>/dev/null

echo ""
echo "========================================"
echo "모니터링 중... (5초마다 체크)"
echo ""

while true; do
    TIMESTAMP=$(date '+%H:%M:%S')
    
    # Fuseki 트리플 수
    TRIPLE_COUNT=$(curl -s -X POST "http://localhost:3030/$FUSEKI_DATASET/query" \
      --data-urlencode "query=SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o }" \
      -H "Accept: application/sparql-results+json" | jq -r '.results.bindings[0].count.value' 2>/dev/null || echo "0")
    
    # MongoDB 문서 수와 상태
    DOC_INFO=$(docker exec ragaas-mongo mongosh -u root -p example --quiet --eval "
    const docs = db.getSiblingDB('ragaas').documents.find({knowledge_base_id: '$KB_ID'}).toArray();
    if (docs.length > 0) {
        const latest = docs[docs.length - 1];
        print(docs.length + '개|' + latest.filename + '|' + latest.status + '|' + (latest.pipeline_status || 'N/A'));
    } else {
        print('0개|없음|N/A|N/A');
    }
    " 2>/dev/null)
    
    DOC_COUNT=$(echo "$DOC_INFO" | cut -d'|' -f1)
    DOC_NAME=$(echo "$DOC_INFO" | cut -d'|' -f2)
    DOC_STATUS=$(echo "$DOC_INFO" | cut -d'|' -f3)
    PIPELINE_STATUS=$(echo "$DOC_INFO" | cut -d'|' -f4)
    
    # 트리플 파일 확인
    TRIPLE_FILES=$(find /Users/dukekimm/Works/RAGaaS/data/uploads/$KB_ID/ -name "*_triples.json" 2>/dev/null | wc -l | tr -d ' ')
    
    echo "[$TIMESTAMP] 📊 Fuseki: ${TRIPLE_COUNT}개 | MongoDB: ${DOC_COUNT} | 파일: ${TRIPLE_FILES}개"
    if [ "$DOC_COUNT" != "0개" ]; then
        echo "           📄 문서: $DOC_NAME"
        echo "           🔄 상태: $DOC_STATUS | Pipeline: $PIPELINE_STATUS"
    fi
    echo ""
    
    sleep 5
done
