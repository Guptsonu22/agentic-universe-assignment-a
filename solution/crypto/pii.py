"""Cryptographic utilities for PII protection: HMAC blind indexing & AES-256-GCM authenticated encryption."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class DecryptionError(Exception):
    """Raised when ciphertext authentication or decryption fails."""


class PIIEngine:
    """Manages cryptographic key derivation, deterministic blind indexing, and AEAD encryption."""

    def __init__(self, master_key: bytes) -> None:
        if len(master_key) < 32:
            raise ValueError("Master key must contain at least 32 bytes of entropy.")
        self._master_key = master_key

        # Derive separate domain-separated 256-bit subkeys via HKDF (RFC 5869)
        self._hmac_key = self._derive_key(b"au-hmac-blind-index-v1")
        self._aes_key = self._derive_key(b"au-aes-gcm-encryption-v1")
        self._aesgcm = AESGCM(self._aes_key)

    def _derive_key(self, context_info: bytes) -> bytes:
        """Derive a dedicated 32-byte key for a specific cryptographic context."""
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"agentic-universe-pii-v1",
            info=context_info,
        )
        return hkdf.derive(self._master_key)

    def compute_blind_index(self, canonical_phone: str) -> str:
        """
        Compute a deterministic keyed HMAC-SHA256 blind index for exact phone matching.
        
        Returns:
            64-character lowercase hex digest.
        """
        if not canonical_phone:
            raise ValueError("Canonical phone cannot be empty for blind indexing.")

        digest = hmac.new(
            self._hmac_key,
            canonical_phone.strip().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return digest

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string using AES-256-GCM with a fresh random 96-bit nonce.
        
        Returns:
            URL-safe Base64-encoded string: base64(nonce || ciphertext || tag).
        """
        if plaintext is None:
            raise ValueError("Plaintext cannot be None.")

        # 96-bit (12 bytes) standard nonce for AES-GCM
        nonce = os.urandom(12)
        plaintext_bytes = plaintext.encode("utf-8")
        ciphertext_and_tag = self._aesgcm.encrypt(nonce, plaintext_bytes, None)

        combined = nonce + ciphertext_and_tag
        return base64.urlsafe_b64encode(combined).decode("ascii")

    def decrypt(self, ciphertext_b64: str) -> str:
        """
        Decrypt and authenticate an AES-256-GCM ciphertext payload.
        
        Raises:
            DecryptionError if the ciphertext has been modified or corrupted.
        """
        if not ciphertext_b64:
            raise ValueError("Ciphertext cannot be empty.")

        try:
            raw_bytes = base64.urlsafe_b64decode(ciphertext_b64.encode("ascii"))
        except Exception as exc:
            raise DecryptionError(f"Malformed base64 ciphertext: {exc}") from exc

        if len(raw_bytes) < 28:  # 12-byte nonce + 16-byte minimum tag
            raise DecryptionError("Ciphertext payload is truncated or too short for AES-GCM.")

        nonce = raw_bytes[:12]
        ciphertext_and_tag = raw_bytes[12:]

        try:
            decrypted_bytes = self._aesgcm.decrypt(nonce, ciphertext_and_tag, None)
            return decrypted_bytes.decode("utf-8")
        except InvalidTag as exc:
            raise DecryptionError("Decryption failed: Authentication tag mismatch or corrupted data.") from exc
        except Exception as exc:
            raise DecryptionError(f"Decryption error: {exc}") from exc


def mask_phone(canonical_phone: str) -> str:
    """
    Format a canonical phone number (+91XXXXXXXXXX) to masked presentation.
    
    Per specification: '+91****** followed by the last 4 digits'.
    Example: '+919876543210' -> '+91******3210'.
    """
    cleaned = canonical_phone.strip()
    if len(cleaned) < 4:
        raise ValueError(f"Phone number too short to mask: '{cleaned}'")
    return f"+91******{cleaned[-4:]}"


# Module-level convenience functions using an explicit key
def compute_blind_index(canonical_phone: str, master_key: bytes) -> str:
    """Module convenience function for computing a blind index."""
    return PIIEngine(master_key).compute_blind_index(canonical_phone)


def encrypt_pii(plaintext: str, master_key: bytes) -> str:
    """Module convenience function for AEAD encryption."""
    return PIIEngine(master_key).encrypt(plaintext)


def decrypt_pii(ciphertext_b64: str, master_key: bytes) -> str:
    """Module convenience function for AEAD decryption."""
    return PIIEngine(master_key).decrypt(ciphertext_b64)

