"""
프로바이더 API.
- Built-in(OpenAI, Anthropic, Google): API Key 암호화 저장, 모델 목록 API 조회 캐시
- Custom: 사용자 정의 프로바이더 등록
"""
import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Union
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.provider import (
    CustomProvider,
    CustomProviderCreate,
    CustomProviderResponse,
    BuiltinProviderConfig,
    BuiltinProviderKeyUpdate,
)
from app.core.encryption import encrypt, decrypt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/providers", tags=["providers"])

_MODELS_JSON = Path(__file__).parent.parent / "config" / "models.json"

BUILTIN_IDS = ("openai", "anthropic", "google")


def _load_builtin_meta() -> dict:
    try:
        with open(_MODELS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load models.json: {e}")
        return {"providers": {}}


def _build_auth(provider_id: str, api_key: str, url: str) -> Tuple[str, dict]:
    """프로바이더별 인증 방식에 맞춰 URL과 헤더 반환."""
    if not api_key:
        return url, {}
    if provider_id == "anthropic":
        return url, {"x-api-key": api_key}
    if provider_id == "google":
        return url, {"x-goog-api-key": api_key}
    return url, {"Authorization": f"Bearer {api_key}"}


def _parse_models_response(data: Union[dict, list]) -> List[str]:
    models: list = []
    if isinstance(data, dict):
        if "data" in data:
            models = [m["id"] for m in data["data"] if isinstance(m, dict) and m.get("id")]
        elif "models" in data:
            raw = data["models"]
            models = [
                m if isinstance(m, str) else (m.get("id") or m.get("name") or "")
                for m in raw
            ]
    elif isinstance(data, list):
        models = [
            m if isinstance(m, str) else (m.get("id") or m.get("name") or "")
            for m in data
        ]
    return sorted({m for m in models if m})


def _is_embedding_model(model_id: str) -> bool:
    """Embedding 모델 여부 휴리스틱 (id 패턴 기준)."""
    lid = model_id.lower()
    if "embedding" in lid or "embed" in lid or lid.startswith("text-embedding"):
        return True
    if "embed-" in lid or "-embed-" in lid:
        return True
    return False


def _filter_models_by_type(models: List[str], model_type: Optional[str]) -> Tuple[List[str], List[str]]:
    """
    model_type에 따라 LLM/Embedding 목록으로 분리.
    - "llm": embedding 제외 목록 반환, embedding 목록은 빈 리스트
    - "embedding": embedding만 반환, llm 목록은 빈 리스트
    - None/"all": 전체를 llm/embedding 둘 다 분리해서 반환
    반환: (llm_models, embedding_models)
    """
    llm_list: List[str] = []
    emb_list: List[str] = []
    for m in models:
        if _is_embedding_model(m):
            emb_list.append(m)
        else:
            llm_list.append(m)
    if model_type == "embedding":
        return ([], emb_list)
    if model_type == "llm":
        return (llm_list, [])
    return (llm_list, emb_list)


# ── GET /api/providers ─────────────────────────────────────────────────────────

@router.get("")
async def list_providers(model_type: Optional[str] = None):
    """
    Built-in + Custom 프로바이더 통합 반환.
    builtin: models.json 메타 + DB의 API Key/캐시된 모델 (models.llm, models.embedding 구분)
    model_type: "llm" | "embedding" | None — 지정 시 해당 타입 지원 프로바이더만 반환 (custom 필터)
    """
    meta = _load_builtin_meta()
    raw_builtin = meta.get("providers", {})

    builtin_result = {}
    for pid in BUILTIN_IDS:
        if pid not in raw_builtin:
            continue
        info = dict(raw_builtin[pid])
        cfg = await BuiltinProviderConfig.find_one({"provider_id": pid})
        info["has_key"] = bool(cfg and cfg.encrypted_key)
        info["models"] = {
            "llm": cfg.cached_models_llm if cfg else [],
            "embedding": cfg.cached_models_embedding if cfg else [],
        }
        if cfg and cfg.cached_at:
            info["cached_at"] = cfg.cached_at.isoformat()
        builtin_result[pid] = info

    custom_docs = await CustomProvider.find_all().to_list()
    if model_type in ("llm", "embedding"):
        custom_docs = [p for p in custom_docs if p.provider_type == model_type or p.provider_type == "both"]
    custom = [
        CustomProviderResponse(
            provider_id=p.provider_id,
            name=p.name,
            base_url=p.base_url,
            model_list=p.model_list,
            provider_type=p.provider_type,
            has_key=bool(p.encrypted_key),
            created_at=p.created_at,
        )
        for p in custom_docs
    ]

    return {
        "builtin": builtin_result,
        "custom": [c.model_dump() for c in custom],
    }


# ── PUT /api/providers/builtin/{provider_id}/key ───────────────────────────────

@router.put("/builtin/{provider_id}/key")
async def update_builtin_provider_key(provider_id: str, payload: BuiltinProviderKeyUpdate):
    """Built-in 프로바이더 API Key 등록/수정. 암호화해 저장."""
    if provider_id not in BUILTIN_IDS:
        raise HTTPException(status_code=404, detail="Unknown built-in provider")
    if not payload.api_key or not payload.api_key.strip():
        raise HTTPException(status_code=422, detail="api_key is required")

    meta = _load_builtin_meta()
    if provider_id not in meta.get("providers", {}):
        raise HTTPException(status_code=404, detail="Provider not found in config")

    try:
        encrypted = encrypt(payload.api_key.strip())
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to encrypt API key")

    cfg = await BuiltinProviderConfig.find_one({"provider_id": provider_id})
    if cfg:
        cfg.encrypted_key = encrypted
        cfg.updated_at = datetime.utcnow()
        await cfg.save()
    else:
        cfg = BuiltinProviderConfig(
            provider_id=provider_id,
            encrypted_key=encrypted,
        )
        await cfg.insert()

    logger.info(f"Built-in provider key updated: {provider_id}")
    return {"provider_id": provider_id, "has_key": True}


# ── POST /api/providers/fetch-models ───────────────────────────────────────────

class FetchModelsRequest(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    provider_id: Optional[str] = None
    model_type: Optional[str] = None  # "llm" | "embedding" | None (all)


@router.post("/fetch-models")
async def fetch_provider_models(payload: FetchModelsRequest):
    """
    프로바이더 API로 모델 목록 조회.
    - provider_id: openai/anthropic/google → DB 저장 키 사용
    - provider_id: custom UUID → CustomProvider 저장 키 사용
    - base_url + api_key: 직접 입력 (캐시 갱신 안 함)
    반환: models, models_changed (캐시와 비교 시 차이 여부), cached (캐시 사용 여부)
    """
    base_url = payload.base_url
    api_key = (payload.api_key or "").strip()
    provider_id = payload.provider_id
    model_type = payload.model_type or "llm"
    use_stored_key = False
    is_builtin = provider_id in BUILTIN_IDS

    if provider_id:
        if is_builtin:
            cfg = await BuiltinProviderConfig.find_one({"provider_id": provider_id})
            if not cfg or not cfg.encrypted_key:
                raise HTTPException(status_code=400, detail=f"API Key가 등록되지 않았습니다. {provider_id} 프로바이더에 키를 등록해주세요.")
            meta = _load_builtin_meta()
            base_url = meta.get("providers", {}).get(provider_id, {}).get("base_url")
            if not base_url:
                raise HTTPException(status_code=500, detail="Provider config missing base_url")
            try:
                api_key = decrypt(cfg.encrypted_key)
            except ValueError:
                raise HTTPException(status_code=500, detail="Failed to decrypt API key")
            use_stored_key = True
        else:
            custom = await CustomProvider.find_one(CustomProvider.provider_id == provider_id)
            if not custom:
                raise HTTPException(status_code=404, detail="Provider not found")
            base_url = custom.base_url
            try:
                api_key = decrypt(custom.encrypted_key)
            except ValueError:
                raise HTTPException(status_code=500, detail="Failed to decrypt API key")
            use_stored_key = True

    if not base_url:
        raise HTTPException(status_code=422, detail="base_url 또는 provider_id가 필요합니다.")

    url = f"{base_url.rstrip('/')}/models"
    url, headers = _build_auth(provider_id or "openai", api_key, url)

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
    except httpx.TimeoutException:
        raise HTTPException(status_code=408, detail="Request timed out")
    except httpx.RequestError as e:
        raise HTTPException(status_code=400, detail=f"Connection error: {e}")

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid API key (401 Unauthorized)")
    if resp.status_code == 403:
        raise HTTPException(status_code=403, detail="Access denied (403 Forbidden)")
    if not resp.is_success:
        raise HTTPException(status_code=resp.status_code, detail=f"Provider returned HTTP {resp.status_code}")

    try:
        data = resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail="Provider returned invalid JSON")

    models = _parse_models_response(data)
    logger.info(f"Fetched {len(models)} models from {base_url}")

    llm_models, emb_models = _filter_models_by_type(models, model_type)
    if model_type == "llm":
        models_to_return = llm_models
    elif model_type == "embedding":
        models_to_return = emb_models
    else:
        models_to_return = models

    models_changed = False
    if use_stored_key and is_builtin and provider_id:
        cfg = await BuiltinProviderConfig.find_one({"provider_id": provider_id})
        if cfg:
            prev_llm = set(cfg.cached_models_llm)
            prev_emb = set(cfg.cached_models_embedding)
            if model_type == "llm":
                new_llm = set(llm_models)
                new_emb = prev_emb
            elif model_type == "embedding":
                new_llm = prev_llm
                new_emb = set(emb_models)
            else:
                new_llm = set(llm_models)
                new_emb = set(emb_models)
            models_changed = prev_llm != new_llm or prev_emb != new_emb

            if model_type == "llm":
                cfg.cached_models_llm = llm_models
            elif model_type == "embedding":
                cfg.cached_models_embedding = emb_models
            else:
                cfg.cached_models_llm = llm_models
                cfg.cached_models_embedding = emb_models
            cfg.cached_at = datetime.utcnow()
            await cfg.save()

    return {
        "models": models_to_return,
        "models_changed": models_changed,
        "cached": use_stored_key,
    }


# ── Custom Provider CRUD ──────────────────────────────────────────────────────

@router.post("/custom", response_model=CustomProviderResponse, status_code=201)
async def create_custom_provider(payload: CustomProviderCreate):
    if not payload.api_key.strip():
        raise HTTPException(status_code=422, detail="api_key is required")
    try:
        encrypted = encrypt(payload.api_key)
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to encrypt API key")

    provider = CustomProvider(
        name=payload.name,
        base_url=payload.base_url.rstrip("/"),
        encrypted_key=encrypted,
        model_list=payload.model_list,
        provider_type=payload.provider_type,
    )
    await provider.insert()
    logger.info(f"Custom provider registered: {provider.name} ({provider.provider_id})")
    return CustomProviderResponse(
        provider_id=provider.provider_id,
        name=provider.name,
        base_url=provider.base_url,
        model_list=provider.model_list,
        provider_type=provider.provider_type,
        has_key=True,
        created_at=provider.created_at,
    )


@router.put("/custom/{provider_id}", response_model=CustomProviderResponse)
async def update_custom_provider(provider_id: str, payload: CustomProviderCreate):
    provider = await CustomProvider.find_one(CustomProvider.provider_id == provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    provider.name = payload.name
    provider.base_url = payload.base_url.rstrip("/")
    provider.model_list = payload.model_list
    provider.provider_type = payload.provider_type
    provider.updated_at = datetime.utcnow()
    if payload.api_key.strip():
        provider.encrypted_key = encrypt(payload.api_key)
    await provider.save()
    return CustomProviderResponse(
        provider_id=provider.provider_id,
        name=provider.name,
        base_url=provider.base_url,
        model_list=provider.model_list,
        provider_type=provider.provider_type,
        has_key=True,
        created_at=provider.created_at,
    )


@router.delete("/custom/{provider_id}", status_code=204)
async def delete_custom_provider(provider_id: str):
    provider = await CustomProvider.find_one(CustomProvider.provider_id == provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    await provider.delete()
    logger.info(f"Custom provider deleted: {provider_id}")


@router.get("/custom/{provider_id}/key")
async def get_decrypted_key(provider_id: str):
    provider = await CustomProvider.find_one(CustomProvider.provider_id == provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    try:
        key = decrypt(provider.encrypted_key)
    except ValueError:
        raise HTTPException(status_code=500, detail="Failed to decrypt API key")
    return {"api_key": key, "base_url": provider.base_url}
