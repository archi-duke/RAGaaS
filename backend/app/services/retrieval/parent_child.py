"""Parent-Child(small-to-big) 검색 치환.

인제스트에서 parent_child / hierarchical 청킹을 고르면 각 child 청크의 Milvus
`metadata`(JSON)에 `parent_id` / `parent_content` 가 저장된다
(ingest_service/app/core/pipeline.py `_chunk_parent_child`, backend text_splitter).
검색은 작은 child 로 정밀하게 찾고, LLM 에는 문맥이 충분한 parent 를 넘기는 것이
이 설계의 핵심인데, 이전엔 검색 쪽에 치환 코드가 없어 일반 청킹과 똑같이 동작했다.

expand_to_parents():
  - 결과 청크들의 Milvus metadata 를 조회해 parent_content 가 있는 것만 치환한다.
    (parent-child 로 인제스트되지 않은 청크는 그대로 — 일반 KB 동작 불변)
  - 같은 parent 를 가리키는 child 들은 하나로 합친다. 순서·점수는 그 parent 의
    최상위 child 기준 (입력 순서 = 이미 점수순).
  - 원래 child 정보는 metadata.child_chunk_ids / matched_child_content 에 남긴다.
  - Milvus 조회 실패·타임아웃 시 입력을 그대로 반환한다 (검색 자체를 깨지 않음).
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MILVUS_QUERY_TIMEOUT_SEC = 10.0


def _parse_metadata(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except ValueError:
            return {}
    return {}


def _fetch_chunk_metadata_sync(kb_id: str, chunk_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    from pymilvus import Collection, utility

    collection_name = f"kb_{kb_id.replace('-', '_')}"
    if not utility.has_collection(collection_name):
        return {}
    collection = Collection(collection_name)
    field_names = {f.name for f in collection.schema.fields}
    if "metadata" not in field_names:
        return {}
    quoted = ", ".join('"' + cid.replace("\\", "\\\\").replace('"', '\\"') + '"' for cid in chunk_ids)
    rows = collection.query(
        expr=f"chunk_id in [{quoted}]",
        output_fields=["chunk_id", "metadata"],
        limit=len(chunk_ids),
    )
    return {r["chunk_id"]: _parse_metadata(r.get("metadata")) for r in rows if r.get("chunk_id")}


def merge_into_parents(
    results: List[Dict[str, Any]],
    chunk_metadata: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """child 결과를 parent 로 치환·병합 (순수 함수 — 테스트 대상)."""
    merged: List[Dict[str, Any]] = []
    parent_slot: Dict[tuple, Dict[str, Any]] = {}

    for r in results:
        cid = r.get("chunk_id")
        meta = chunk_metadata.get(cid) if cid else None
        parent_content = (meta or {}).get("parent_content")
        if not parent_content:
            merged.append(r)
            continue

        doc_id = (r.get("metadata") or {}).get("doc_id") or r.get("doc_id") or meta.get("doc_id") or ""
        parent_id = meta.get("parent_id", meta.get("parent_index"))
        key = (doc_id, str(parent_id))

        existing = parent_slot.get(key)
        if existing is not None:
            existing["metadata"]["child_chunk_ids"].append(cid)
            continue

        new_r = dict(r)
        new_meta = dict(r.get("metadata") or {})
        new_meta["parent_id"] = parent_id
        new_meta["child_chunk_ids"] = [cid]
        new_meta["matched_child_content"] = r.get("content", "")
        new_meta["retrieval_unit"] = "parent"
        new_r["metadata"] = new_meta
        new_r["content"] = parent_content
        parent_slot[key] = new_r
        merged.append(new_r)

    return merged


async def expand_to_parents(
    kb_id: str,
    results: List[Dict[str, Any]],
    logs: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """검색 결과의 child 청크를 parent 로 치환. 대상이 없거나 실패하면 입력 그대로."""
    if not results:
        return results
    chunk_ids = [
        r["chunk_id"] for r in results
        if r.get("chunk_id") and r.get("chunk_id") != "GRAPH_METADATA_ONLY"
    ]
    if not chunk_ids:
        return results

    try:
        chunk_metadata = await asyncio.wait_for(
            asyncio.to_thread(_fetch_chunk_metadata_sync, kb_id, list(dict.fromkeys(chunk_ids))),
            timeout=MILVUS_QUERY_TIMEOUT_SEC,
        )
    except Exception as e:  # 타임아웃·스키마 불일치 등 — 검색을 깨지 않는다
        logger.warning(f"[ParentChild] metadata lookup failed, keeping child chunks: {e}")
        if logs is not None:
            logs.append(f"[ParentChild] metadata lookup failed, keeping child chunks: {e}")
        return results

    if not any((m or {}).get("parent_content") for m in chunk_metadata.values()):
        return results

    merged = merge_into_parents(results, chunk_metadata)
    if logs is not None:
        n_parent = sum(1 for r in merged if (r.get("metadata") or {}).get("retrieval_unit") == "parent")
        logs.append(
            f"[ParentChild] {len(results)} child results → {len(merged)} results ({n_parent} parent chunks)"
        )
    return merged
