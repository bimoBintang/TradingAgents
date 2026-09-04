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

# True when running on a throwaway key, i.e. every stored credential
# becomes unreadable at the next restart.
IS_EPHEMERAL_KEY = not bool(_env_keys)

if _env_keys:
    # Support multiple keys separated by comma for key rotation.
    # The first key is the primary key used for encryption.
    for k in _env_keys.split(","):
        k = k.strip()
        if k:
            key_bytes = k.encode() if isinstance(k, str) else k
            _fernet_instances.append(Fernet(key_bytes))
else:
    # Refuse to start a production deployment on an ephemeral key.
    #
    # The failure mode this prevents is quiet, not loud: within a single
    # process run the ephemeral key works perfectly, so a user can save
    # exchange credentials, trade live, and see everything succeed. After
    # the next restart those credentials silently fail to decrypt, the
    # account falls back to paper (safe, by design) — and nothing tells
    # the user their "live" bot stopped being live. Better to refuse to
    # boot than to run a trading system whose credential store evaporates
    # on every deploy.
    if os.environ.get("ENVIRONMENT", "").lower() in ("production", "prod"):
        raise RuntimeError(
            "FERNET_KEY is required when ENVIRONMENT=production. Without it, stored "
            "exchange API credentials become unreadable after every restart and live "
            "trading silently reverts to paper. Generate one with:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )

    logger.critical(
        "FERNET_KEY not set — using an EPHEMERAL key. Stored API credentials will be "
        "UNREADABLE after this process restarts, and live trading will silently fall "
        "back to paper. This is acceptable for local development ONLY. "
        "Set FERNET_KEY in .env before trading real money."
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
