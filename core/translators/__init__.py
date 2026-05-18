"""Translation backends. Currently: NLLB-200 (local, free, 200 languages)."""
from core.translators.nllb import (
    translate as nllb_translate,
    is_available as nllb_available,
    detect_source_language,
    supported_languages,
)

__all__ = [
    "nllb_translate",
    "nllb_available",
    "detect_source_language",
    "supported_languages",
]
