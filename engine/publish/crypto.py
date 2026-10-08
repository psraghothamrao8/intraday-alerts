"""
Encryption and decryption for dashboard state publishing.
Implements PBKDF2-HMAC-SHA256 (310,000 iterations) + AES-256-GCM per spec 04 §7.2.
"""
import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

AAD = b"intraday-state-v1"
SALT_FILE = Path("secrets/state_salt.bin")
PBKDF2_ITERATIONS = 310_000


def get_or_create_salt(salt_path: Path | str = SALT_FILE) -> bytes:
    """Load 16-byte salt from secrets/state_salt.bin or generate and persist it."""
    path = Path(salt_path)
    if path.exists():
        salt = path.read_bytes()
        if len(salt) == 16:
            return salt
    path.parent.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(16)
    path.write_bytes(salt)
    return salt


def derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive 32-byte AES key via PBKDF2-HMAC-SHA256 with 310,000 iterations."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_payload(
    plaintext_data: Dict[str, Any] | str,
    passphrase: str,
    salt: Optional[bytes] = None,
    iv: Optional[bytes] = None
) -> Tuple[str, str, str]:
    """
    Encrypt data using AES-256-GCM.
    Returns (salt_b64, iv_b64, ct_b64).
    """
    if salt is None:
        salt = get_or_create_salt()
    if iv is None:
        iv = os.urandom(12)

    key = derive_key(passphrase, salt)
    aesgcm = AESGCM(key)

    if isinstance(plaintext_data, (dict, list)):
        plaintext_bytes = json.dumps(plaintext_data, ensure_ascii=False).encode("utf-8")
    else:
        plaintext_bytes = str(plaintext_data).encode("utf-8")

    # AESGCM.encrypt appends 16-byte authentication tag to the ciphertext
    ct_with_tag = aesgcm.encrypt(iv, plaintext_bytes, AAD)

    salt_b64 = base64.b64encode(salt).decode("ascii")
    iv_b64 = base64.b64encode(iv).decode("ascii")
    ct_b64 = base64.b64encode(ct_with_tag).decode("ascii")

    return salt_b64, iv_b64, ct_b64


def decrypt_payload(
    salt_b64: str,
    iv_b64: str,
    ct_b64: str,
    passphrase: str
) -> Dict[str, Any]:
    """
    Decrypt base64-encoded salt, iv, and ct_with_tag using passphrase.
    Returns parsed JSON dictionary.
    """
    salt = base64.b64decode(salt_b64)
    iv = base64.b64decode(iv_b64)
    ct_with_tag = base64.b64decode(ct_b64)

    key = derive_key(passphrase, salt)
    aesgcm = AESGCM(key)

    plaintext_bytes = aesgcm.decrypt(iv, ct_with_tag, AAD)
    return json.loads(plaintext_bytes.decode("utf-8"))
