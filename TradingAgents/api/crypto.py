"""Fernet symmetric encryption for API credentials.

API Keys and Secrets are encrypted before being stored in the database
and decrypted only when needed (e.g., to initialise a CCXT broker).

The encryption key MUST be set via the FERNET_KEY environment variable
in production. If absent, a random key is generated (useful for dev,
but means data is lost on restart).
"""

import os
import logging
from cryptography.fernet import Fernet, MultiFernet, InvalidToken

logger = logging.getLogger("api.crypto")

# ── Key Management ────────────────────────────────────────────────────

_env_keys = os.environ.get("FERNET_KEY")

_fernet_instances = []

if _env_keys:
    # Support multiple keys separated by comma for key rotation.
    # The first key is the primary key used for encryption.
    for k in _env_keys.split(","):
        k = k.strip()
        if k:
            key_bytes = k.encode() if isinstance(k, str) else k
            _fernet_instances.append(Fernet(key_bytes))
else:
    logger.warning(
        "FERNET_KEY not set — generating ephemeral key. "
        "Encrypted data will be UNREADABLE after restart. "
        "Set FERNET_KEY in your .env for persistence. "
        "Separate multiple keys with commas for key rotation."
    )
    _fernet_instances.append(Fernet(Fernet.generate_key()))

# MultiFernet handles key rotation automatically.
# It encrypts using the FIRST key in the list,
# and attempts decryption using ALL keys in the list.
_cipher = MultiFernet(_fernet_instances)


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
