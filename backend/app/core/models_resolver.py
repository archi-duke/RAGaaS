from typing import Optional, Dict, Any
import os
import re
import json
import logging
from pathlib import Path

from app.models.provider import CustomProvider, BuiltinProviderConfig
from app.core.encryption import decrypt

logger = logging.getLogger(__name__)

BUILTIN_IDS = ("openai", "anthropic", "google")
INTERNAL_ID = "internal"
_MODELS_JSON = Path(__file__).parent.parent / "config" / "models.json"
_INTERNAL_JSON = Path(__file__).parent.parent / "config" / "internal_models.json"


def load_internal_models() -> dict:
    """사내 게이트웨이 모델 설정(config/internal_models.json)을 로드한다.

    모델별로 endpoint 가 다른 사내 LLM 들을 파일에 나열해두고 참조한다.
    파일이 없으면 빈 설정을 반환한다(사외 배포 시 무해).
    """
    try:
        with open(_INTERNAL_JSON, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except FileNotFoundError:
        return {"shared_headers": {}, "models": []}
    except Exception as e:
        logger.error(f"Failed to load internal_models.json: {e}")
        return {"shared_headers": {}, "models": []}
    meta.setdefault("shared_headers", {})
    meta.setdefault("models", [])
    return meta

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: Any) -> Any:
    """문자열 안의 ${VAR} 를 환경변수 값으로 치환한다.

    사내 게이트웨이 티켓 등 시크릿을 DB 평문 대신 환경변수로 주입하기 위함.
    예: extra_headers = {"X-Dep-Ticket": "${LLM_DEP_TICKET}"} → 실제 티켓 값.
    미정의 환경변수는 원본 그대로 둔다(오탈자 시 빈 값으로 조용히 죽는 것 방지).
    """
    if not isinstance(value, str) or "${" not in value:
        return value
    return _ENV_PATTERN.sub(lambda m: os.getenv(m.group(1), m.group(0)), value)


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
    - fallback 없음: 설정이 없으면 api_key는 None
    """
    api_key = None
    base_url = None
    model = default_model
    extra_headers: Dict[str, str] = {}

    if not config:
        return {
            "model": model, "api_key": api_key, "base_url": base_url,
            "extra_headers": extra_headers, "embedding_request_format": "openai",
        }

    model = config.get("model", model)
    provider = config.get("provider")
    provider_id = config.get("provider_id")

    embedding_request_format = "openai"
    # 사내 게이트웨이 모델 (config/internal_models.json 참조) — 모델별 endpoint 상이
    if provider_id == INTERNAL_ID or provider == INTERNAL_ID:
        meta = load_internal_models()
        entry = next((m for m in meta.get("models", []) if m.get("name") == model), None)
        if entry:
            base_url = entry.get("endpoint")
            extra_headers = {**(meta.get("shared_headers") or {}), **(entry.get("headers") or {})}
            if entry.get("api_key"):
                api_key = entry["api_key"]
            embedding_request_format = entry.get("embedding_request_format", embedding_request_format)
        else:
            logger.error(f"internal model '{model}' not found in internal_models.json")
    # Custom 프로바이더 (provider_id가 UUID 형식)
    elif provider_id and provider_id not in BUILTIN_IDS:
        custom = await CustomProvider.find_one({"provider_id": provider_id})
        if custom:
            base_url = custom.base_url
            extra_headers = getattr(custom, "extra_headers", None) or {}
            embedding_request_format = getattr(custom, "embedding_request_format", "openai") or "openai"
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
    if config.get("embedding_request_format"):
        embedding_request_format = config["embedding_request_format"]

    # 시크릿(사내 게이트웨이 티켓 등)을 환경변수로 주입할 수 있도록 ${VAR} 치환.
    api_key = _expand_env(api_key)
    base_url = _expand_env(base_url)
    extra_headers = {k: _expand_env(v) for k, v in (extra_headers or {}).items()}

    return {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "extra_headers": extra_headers,
        "embedding_request_format": embedding_request_format,
    }
