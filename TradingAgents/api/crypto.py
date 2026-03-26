"""Fernet symmetric encryption for API credentials.

API Keys and Secrets are encrypted before being stored in the database
and decrypted only when needed (e.g., to initialise a CCXT broker).

The encryption key MUST be set via the FERNET_KEY environment variable
in production. If absent, a random key is generated (useful for dev,
but means data is lost on restart).
"""

import os
import logging
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("api.crypto")

# ── Key Management ────────────────────────────────────────────────────

_env_key = os.environ.get("FERNET_KEY")

if _env_key:
    _KEY = _env_key.encode() if isinstance(_env_key, str) else _env_key
else:
    logger.warning(
        "FERNET_KEY not set — generating ephemeral key. "
        "Encrypted data will be UNREADABLE after restart. "
        "Set FERNET_KEY in your .env for persistence."
    )
    _KEY = Fernet.generate_key()

_cipher = Fernet(_KEY)


# ── Public API ────────────────────────────────────────────────────────

def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns base64-encoded ciphertext."""
    if not plaintext:
        return ""
    return _cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext string."""
    if not ciphertext:
        return ""
    try:
        return _cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error(
            "Failed to decrypt credential — FERNET_KEY may have changed. "
            "The user will need to re-enter their API keys."
        )
        return ""
