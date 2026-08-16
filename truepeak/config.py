import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() not in ("0", "false", "no", "off")


class Config:
    HOST = os.environ.get("TRUEPEAK_HOST", "127.0.0.1")
    PORT = _env_int("TRUEPEAK_PORT", 5000)
    TEMP_DIR = Path(os.environ.get("TRUEPEAK_TEMP_DIR", str(BASE_DIR / "temp")))
    # Master WAV files can be large; keep the limit configurable for hosted use.
    MAX_CONTENT_LENGTH = _env_int("TRUEPEAK_MAX_UPLOAD_MB", 2048) * 1024 * 1024
    RATE_LIMIT_ENABLED = _env_bool("TRUEPEAK_RATE_LIMIT", True)
    RATE_LIMIT_MAX_CALLS = _env_int("TRUEPEAK_RATE_MAX_CALLS", 10)
    RATE_LIMIT_PER_SECONDS = _env_int("TRUEPEAK_RATE_PER_SECONDS", 60)
    MAX_DURATION_MINUTES = _env_float("TRUEPEAK_MAX_DURATION_MINUTES", 180.0)
    MAX_NORMALIZE_DURATION_MINUTES = _env_float("TRUEPEAK_MAX_NORMALIZE_MINUTES", 180.0)
    NORMALIZE_TOKEN_TTL_SECONDS = _env_int("TRUEPEAK_NORMALIZE_TTL_SECONDS", 600)
    # Branding for reports/UI (own-studio white label).
    BRAND_NAME = os.environ.get("TRUEPEAK_BRAND_NAME", "")
    BRAND_LOGO = os.environ.get("TRUEPEAK_BRAND_LOGO", "")
    TESTING = False
