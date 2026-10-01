"""Window-scoped editor translations; project content is never translated."""

from functools import lru_cache
import json
from pathlib import Path
import sys


@lru_cache(maxsize=1)
def _english():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    with (root / "i18n" / "editor_en.json").open(encoding="utf-8") as stream:
        return json.load(stream)


def localize(text, owner):
    """Resolve language from this widget's owning window, never global settings."""
    while owner is not None:
        language = getattr(owner, "lang_key", None)
        if language is not None:
            return _english().get(text, text) if language == "en" else text
        parent = getattr(owner, "parent", None)
        owner = parent() if callable(parent) else None
    return text
