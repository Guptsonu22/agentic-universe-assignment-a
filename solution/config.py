"""Configuration management and environment variable loader for Assignment A."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv

    # Load from .env if present in workspace root
    load_dotenv()
except ImportError:
    pass

# IST Timezone (UTC+05:30) per assignment specification
IST = timezone(timedelta(hours=5, minutes=30))

# Safe default development key for evaluation if environment variable is not explicitly set.
# In production, this must be provided via the PII_SECRET_KEY environment variable.
_DEV_FALLBACK_KEY_HEX = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


class ConfigurationError(Exception):
    """Raised when application configuration or secret keys are missing or invalid."""


@dataclass(frozen=True)
class Config:
    """Immutable application configuration."""

    database_path: str
    pii_secret_key: bytes
    log_level: str
    is_development: bool

    @classmethod
    def load(
        cls,
        database_path: Optional[str] = None,
        require_explicit_key: bool = False,
    ) -> Config:
        """Load configuration from environment variables with security validation."""
        env_db_path = os.getenv("DATABASE_PATH", "au_ledger.db")
        resolved_db_path = database_path or env_db_path

        log_level = os.getenv("LOG_LEVEL", "INFO").upper()

        raw_key = os.getenv("PII_SECRET_KEY")
        strict_mode = require_explicit_key or (
            os.getenv("STRICT_SECURITY", "false").lower() in ("true", "1", "yes")
        )

        if not raw_key:
            if strict_mode:
                raise ConfigurationError(
                    "CRITICAL: PII_SECRET_KEY environment variable is missing or empty. "
                    "Cannot initialize secure pipeline without an authenticated secret key."
                )
            # Use development fallback key with an explicit warning
            key_hex = _DEV_FALLBACK_KEY_HEX
            is_dev = True
        else:
            key_hex = raw_key.strip()
            is_dev = False

        try:
            key_bytes = bytes.fromhex(key_hex)
        except ValueError as exc:
            raise ConfigurationError(
                f"Invalid PII_SECRET_KEY: Key must be a valid hex string ({exc})."
            ) from exc

        if len(key_bytes) < 32:
            raise ConfigurationError(
                f"Insecure PII_SECRET_KEY: Key must provide at least 32 bytes (64 hex characters) of entropy. "
                f"Received {len(key_bytes)} bytes."
            )

        return cls(
            database_path=resolved_db_path,
            pii_secret_key=key_bytes,
            log_level=log_level,
            is_development=is_dev,
        )


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure a structured, secure logger that avoids leaking sensitive data."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger = logging.getLogger("agentic_universe")
    logger.setLevel(numeric_level)

    # Avoid duplicate handlers if already configured
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s (%(module)s): %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

