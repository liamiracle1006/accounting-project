"""
AgentLedger V4.0 — Field-level encryption utilities

使用 Fernet（AES-128-CBC + HMAC-SHA256）对敏感字段（如申报密码）进行
可逆加密存储。密钥通过环境变量 FIELD_ENCRYPTION_KEY 注入（Base64URL 编码）。

若未配置密钥，开发环境退化为明文存储并打印警告，不影响其他功能。
生产环境必须设置此变量，否则 tax_password 以明文落库存在安全风险。
"""
import base64
import logging
import os

logger = logging.getLogger(__name__)

_fernet = None
_WARN_ISSUED = False


def _get_fernet():
    global _fernet, _WARN_ISSUED
    if _fernet is not None:
        return _fernet

    raw_key = os.getenv("FIELD_ENCRYPTION_KEY", "")
    if not raw_key:
        if not _WARN_ISSUED:
            logger.warning(
                "FIELD_ENCRYPTION_KEY 未配置 — tax_password 将以明文存储。"
                "生产环境请在 .env 中设置 32 字节随机密钥（Fernet 格式）。"
            )
            _WARN_ISSUED = True
        return None

    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(raw_key.encode())
        return _fernet
    except Exception as exc:
        logger.error("FIELD_ENCRYPTION_KEY 格式无效: %s", exc)
        return None


def encrypt_field(plaintext: str) -> str:
    """加密字段值。若密钥未配置，返回原文（前缀 'plain:' 标记）。"""
    f = _get_fernet()
    if f is None:
        return f"plain:{plaintext}"
    encrypted = f.encrypt(plaintext.encode())
    return encrypted.decode()


def decrypt_field(ciphertext: str) -> str:
    """解密字段值。自动识别 'plain:' 前缀（无密钥退化模式）。"""
    if ciphertext.startswith("plain:"):
        return ciphertext[6:]
    f = _get_fernet()
    if f is None:
        logger.error("无法解密：FIELD_ENCRYPTION_KEY 未配置，但数据库中存储了加密值")
        return ""
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except Exception as exc:
        logger.error("字段解密失败: %s", exc)
        return ""
