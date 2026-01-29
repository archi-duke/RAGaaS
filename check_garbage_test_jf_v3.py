
import os
from pymongo import MongoClient
import requests
from pymilvus import connections, utility, Collection

def check_garbage_final(kb_id: str):
    print(f"--- Checking garbage for KB: {kb_id} ---")
    
    # MongoDB 연결
    mongo_client = MongoClient("mongodb://root:example@localhost:27017")
    db = mongo_client.ragaas

    # 1. MongoDB - Documents 컬렉션 확인
    try:
        docs = list(db.documents.find({"kb_id": kb_id}))
        print(f"[MongoDB] Documents found: {len(docs)}")
        for doc in docs:
            print(f"  - Doc ID: {doc.get('id')}, Filename: {doc.get('filename')}, Status: {doc.get('status')}")
    except Exception as e:
        print(f"[MongoDB-Docs] Error: {e}")

    # 2. MongoDB - TripleChunkMapping 확인
    try:
        mappings = list(db.triple_chunk_mapping.find({"kb_id": kb_id}))
        print(f"[MongoDB] TripleChunkMapping found: {len(mappings)}")
        if mappings:
            doc_ids = set(m.get("doc_id") for m in mappings)
            print(f"  - Linked to Doc IDs: {doc_ids}")
    except Exception as e:
        print(f"[MongoDB-Mappings] Error: {e}")

    # 3. Milvus 확인
    try:
        # Docker 내부 호스트가 아닐 수 있으므로 localhost 시도
        connections.connect("default", host="localhost", port="19530")
        collection_name = f"kb_{kb_id.replace('-', '_')}"
        if utility.has_collection(collection_name):
            col = Collection(collection_name)
            # Milvus는 flush/loading 상태에 따라 다를 수 있으나 간단히 엔티티 수 확인
            print(f"[Milvus] Collection '{collection_name}' exists.")
            # query로 kb_id에 해당하는 데이터가 있는지 확인 (컬렉션 자체가 KB 단위가 아닐 경우를 대비)
            # 여기서는 컬렉션 이름에 kb_id가 포함되므로 전체 카운트 확인
            try:
                col.load()
                count = col.num_entities
                print(f"  - Entity count: {count}")
            except:
                print("  - Could not get entity count (empty or not loaded)")
        else:
            print(f"[Milvus] Collection '{collection_name}' does NOT exist.")
    except Exception as e:
        print(f"[Milvus] Error: {e}")

    # 4. Fuseki 확인 (데이터셋 자체가 kb_id인 경우)
    fuseki_url = f"http://localhost:3030/{kb_id}/query"
    query = "SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o }"
    try:
        resp = requests.post(fuseki_url, data={"query": query}, timeout=5)
        if resp.status_code == 200:
            count = resp.json()["results"]["bindings"][0]["count"]["value"]
            print(f"[Fuseki] Triples found in dataset: {count}")
        else:
            print(f"[Fuseki] Dataset check failed (Status {resp.status_code}). Might be using default graph or named graphs.")
            # Named Graph 확인 시도 (전체 카운트)
            query_all = "SELECT (COUNT(*) as ?count) WHERE { GRAPH ?g { ?s ?p ?o } }"
            resp_all = requests.post(fuseki_url, data={"query": query_all}, timeout=5)
            if resp_all.status_code == 200:
                count_all = resp_all.json()["results"]["bindings"][0]["count"]["value"]
                print(f"[Fuseki] Triples found in all Named Graphs: {count_all}")
    except Exception as e:
        print(f"[Fuseki] Error: {e}")

    mongo_client.close()

if __name__ == "__main__":
    KB_ID = "4ba60b29-cfd3-4c04-969a-bfa64d6a46e1"
    check_garbage_final(KB_ID)
