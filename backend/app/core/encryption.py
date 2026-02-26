"""
Fernet 기반 대칭키 암호화 유틸리티.
Custom Provider의 API Key를 MongoDB에 저장하기 전에 암호화합니다.
"""
import logging
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from app.core.config import settings

logger = logging.getLogger(__name__)

_fernet: Optional[Fernet] = None



def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = settings.ENCRYPTION_KEY.strip()
        if not key:
            # 경고: 재시작마다 새 키가 생성되므로 기존 암호화 값을 복호화할 수 없습니다.
            logger.warning(
                "[Encryption] ENCRYPTION_KEY is not set. "
                "Generating a temporary key — stored keys will be lost on restart. "
                "Set ENCRYPTION_KEY in .env for production use."
            )
            key = Fernet.generate_key().decode()
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt(plaintext: str) -> str:
    """평문 문자열을 Fernet으로 암호화하여 base64 문자열로 반환합니다."""
    token = _get_fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt(ciphertext: str) -> str:
    """Fernet으로 암호화된 문자열을 복호화하여 반환합니다."""
    try:
        plaintext = _get_fernet().decrypt(ciphertext.encode("utf-8"))
        return plaintext.decode("utf-8")
    except InvalidToken as e:
        logger.error("[Encryption] Failed to decrypt token — key mismatch or corrupted data.")
        raise ValueError("Failed to decrypt API key. ENCRYPTION_KEY may have changed.") from e
