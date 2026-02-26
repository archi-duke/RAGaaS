from typing import Optional, Dict, Any
import os
import json
import logging
from pathlib import Path

from app.models.provider import CustomProvider, BuiltinProviderConfig
from app.core.encryption import decrypt

logger = logging.getLogger(__name__)

BUILTIN_IDS = ("openai", "anthropic", "google")
_MODELS_JSON = Path(__file__).parent.parent / "config" / "models.json"


def _load_builtin_meta() -> dict:
    try:
        with open(_MODELS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load models.json: {e}")
        return {"providers": {}}


async def resolve_model_config(config: Optional[dict], default_model: str = "gpt-4o-mini"):
    """
    ModelConfig 딕셔너리를 기반으로 {model, api_key, base_url} 반환.
    - Built-in(openai/anthropic/google): BuiltinProviderConfig에서 암호화된 키 조회
    - Custom: provider_id로 CustomProvider에서 조회
    - fallback: OPENAI_API_KEY env (openai만)
    """
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = None
    model = default_model

    if not config:
        return {"model": model, "api_key": api_key, "base_url": base_url}

    model = config.get("model", model)
    provider = config.get("provider")
    provider_id = config.get("provider_id")

    # Custom 프로바이더 (provider_id가 UUID 형식)
    if provider_id and provider_id not in BUILTIN_IDS:
        custom = await CustomProvider.find_one({"provider_id": provider_id})
        if custom:
            base_url = custom.base_url
            try:
                api_key = decrypt(custom.encrypted_key)
            except Exception as e:
                logger.error(f"Failed to decrypt API key for custom {provider_id}: {e}")
    # Built-in 프로바이더
    elif provider in BUILTIN_IDS:
        meta = _load_builtin_meta()
        info = meta.get("providers", {}).get(provider, {})
        base_url = info.get("base_url")
        cfg = await BuiltinProviderConfig.find_one({"provider_id": provider})
        if cfg and cfg.encrypted_key:
            try:
                api_key = decrypt(cfg.encrypted_key)
            except Exception as e:
                logger.error(f"Failed to decrypt API key for builtin {provider}: {e}")

    if config.get("api_key"):
        api_key = config.get("api_key")
    if config.get("base_url"):
        base_url = config.get("base_url")

    return {"model": model, "api_key": api_key, "base_url": base_url}
