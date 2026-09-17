from functools import lru_cache
from pathlib import Path

_FALLBACK_VERSION = "0.1.0-phase1-foundation"


@lru_cache(maxsize=1)
def get_version() -> str:
    """Return the repository version without requiring package metadata."""
    version_file = Path(__file__).resolve().parents[2] / "VERSION"
    try:
        value = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return _FALLBACK_VERSION
    return value or _FALLBACK_VERSION
