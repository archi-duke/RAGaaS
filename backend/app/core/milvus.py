import asyncio
import logging
from typing import Any, Callable

from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType, utility
from app.core.config import settings

logger = logging.getLogger(__name__)

# 검색 경로의 Milvus 호출 시간 한도 (초).
# pymilvus 호출은 동기 블로킹이라 async 경로에서 그대로 부르면, 서버가 컬렉션을 load 하지 못하고
# 멈춘 동안 이벤트 루프 전체가 묶여 백엔드가 모든 요청에 응답하지 않는다
# (2026-11-22 shared-infra 재시작 후 컬렉션 3개가 Loading 0% 에서 멈춤 → /retrieve 한 번에 백엔드 전체 정지).
MILVUS_LOAD_TIMEOUT = 15
MILVUS_OP_TIMEOUT = 20


class MilvusUnavailableError(RuntimeError):
    """Milvus 호출이 시간 안에 끝나지 않았거나 서버에 연결할 수 없을 때."""


def connect_milvus():
    connections.connect(
        alias="default", 
        host=settings.MILVUS_HOST, 
        port=settings.MILVUS_PORT,
        timeout=10,
    )


def ensure_milvus_connection():
    """연결이 없으면 다시 맺는다. 기동 시 Milvus 가 아직 준비되지 않아 connect 가 실패하면
    이후 모든 호출이 'should create connection first' 로 실패하던 문제 대응."""
    if not connections.has_connection("default"):
        logger.warning("[Milvus] 연결 없음 — 재연결 시도")
        connect_milvus()


def load_collection(kb_id: str) -> Collection:
    """KB 컬렉션을 load 해서 돌려준다 (동기 — 반드시 run_milvus 안에서 호출)."""
    ensure_milvus_connection()
    collection = Collection(f"kb_{kb_id.replace('-', '_')}")
    collection.load(timeout=MILVUS_LOAD_TIMEOUT)
    return collection


async def run_milvus(fn: Callable[..., Any], *args, timeout: float = MILVUS_LOAD_TIMEOUT + MILVUS_OP_TIMEOUT,
                     what: str = "Milvus 호출", **kwargs) -> Any:
    """동기 pymilvus 작업을 스레드로 넘기고 시간 한도를 건다. 실패는 MilvusUnavailableError 로 통일.

    스레드 안의 호출 자체는 취소되지 않으므로, fn 안의 load/search/query 에도 timeout 인자를 준다.
    """
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout=timeout)
    except asyncio.TimeoutError as e:
        raise MilvusUnavailableError(f"{what} 시간 초과({timeout:.0f}초) — Milvus 컬렉션이 로드되지 않았을 수 있습니다") from e
    except MilvusUnavailableError:
        raise
    except Exception as e:
        from pymilvus.exceptions import MilvusException
        if isinstance(e, MilvusException):
            raise MilvusUnavailableError(f"{what} 실패: {str(e)[:300]}") from e
        raise

def create_collection(kb_id: str, metric_type: str = "COSINE", index_type: str = "IVF_FLAT"):
    # Ensure Milvus connection is active (auto-reconnect if needed)
    try:
        # Try to list collections as a connection health check
        utility.list_collections()
    except Exception as e:
        print(f"[Milvus] Connection lost or not established: {e}. Reconnecting...")
        try:
            connections.disconnect(alias="default")
        except:
            pass
        connect_milvus()
        print("[Milvus] Reconnected successfully")
    
    collection_name = f"kb_{kb_id.replace('-', '_')}"
    
    if utility.has_collection(collection_name):
        col = Collection(collection_name)
        # Check if metadata field exists
        has_metadata = any(field.name == "metadata" for field in col.schema.fields)
        if not has_metadata:
            print(f"Collection {collection_name} has outdated schema (missing metadata). Dropping and recreating.")
            utility.drop_collection(collection_name)
        else:
            # Check if index type matches
            if col.has_index():
                idx = col.index()
                current_type = idx.params.get("index_type")
                if current_type != index_type:
                    print(f"Index type mismatch: {current_type} vs {index_type}. Recreating index.")
                    try:
                        col.release()
                    except:
                        pass
                    col.drop_index()
                else:
                    return col
            else:
                # No index, will create below
                pass
            
            if not col.has_index():
                _create_index(col, metric_type, index_type)
            return col
    
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="metadata", dtype=DataType.JSON),
        FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=1536) # Assuming OpenAI embedding dim
    ]
    
    schema = CollectionSchema(fields, "Knowledge Base Collection")
    collection = Collection(collection_name, schema)
    _create_index(collection, metric_type, index_type)
    return collection

def _create_index(collection, metric_type, index_type):
    index_params = {
        "metric_type": metric_type,
        "index_type": index_type,
        "params": {}
    }
    
    if index_type == "IVF_FLAT":
        index_params["params"] = {"nlist": 1024}
    elif index_type == "HNSW":
        index_params["params"] = {"M": 16, "efConstruction": 200}
    elif index_type == "LSH":
        index_params["params"] = {"nbits": 8}
    elif index_type == "FLAT":
        index_params["params"] = {}
        
    collection.create_index(field_name="vector", index_params=index_params)
