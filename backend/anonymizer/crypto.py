import base64
import hashlib
import json
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet():
    digest = hashlib.sha256(settings.MAPPING_ENCRYPTION_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_mapping(mapping):
    payload = json.dumps(mapping, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _fernet().encrypt(payload).decode("ascii")


def decrypt_mapping(ciphertext):
    try:
        payload = _fernet().decrypt(ciphertext.encode("ascii"))
    except (InvalidToken, ValueError) as exc:
        raise ValueError("映射数据无法解密，请确认部署密钥未发生变化。") from exc
    return json.loads(payload.decode("utf-8"))

