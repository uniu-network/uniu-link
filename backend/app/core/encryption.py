from cryptography.fernet import Fernet
import base64
import hashlib

from app.core.config import settings


class KeyEncryption:

    def __init__(self):
        self._fernet: Fernet | None = None

    def _get_fernet(self) -> Fernet:
        if self._fernet is None:
            key = settings.encryption_key
            if not key:
                raise RuntimeError("encryption_key is required for API key encryption")
            elif len(key) < 32:
                digest = hashlib.sha256(key.encode()).digest()
                key = base64.urlsafe_b64encode(digest)
            else:
                if isinstance(key, str):
                    try:
                        Fernet(key.encode())
                    except Exception:
                        digest = hashlib.sha256(key.encode()).digest()
                        key = base64.urlsafe_b64encode(digest)
                    else:
                        key = key.encode()
            self._fernet = Fernet(key)
        return self._fernet

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        f = self._get_fernet()
        return f.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        f = self._get_fernet()
        return f.decrypt(ciphertext.encode()).decode()


key_encryption = KeyEncryption()
