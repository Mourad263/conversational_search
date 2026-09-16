"""Shared EN/AR text normalization used by canonicalization (Sprint 0) and
the search engine's tokenizer (Sprint 1) -- research.md §2/§5/§6 all specify
the same rules, kept in one place so they can't drift apart.
"""

from __future__ import annotations

import re
import unicodedata

_ARABIC_RANGE = re.compile(r"[؀-ۿݐ-ݿ]")
_ARABIC_DIACRITICS = re.compile(r"[ً-ْٰ]")
_TATWEEL = "ـ"
_ALEF_VARIANTS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي"})
_WHITESPACE = re.compile(r"\s+")


def is_arabic(text: str) -> bool:
    return bool(_ARABIC_RANGE.search(text))


def normalize_latin(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).strip().lower()
    text = _WHITESPACE.sub(" ", text)
    return text.strip(" .,-_")


def normalize_arabic(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).strip()
    text = _ARABIC_DIACRITICS.sub("", text)
    text = text.replace(_TATWEEL, "")
    text = text.translate(_ALEF_VARIANTS)
    text = _WHITESPACE.sub(" ", text)
    return text.strip(" .,-_")


def normalize_category_name(text: str) -> str:
    """Category canonicalization normalizes the English name only (research.md
    §5) -- lowercase/whitespace-collapse but keep '&' as a meaningful token
    ('Meat & Poultry' must stay distinct from 'Meat')."""
    text = unicodedata.normalize("NFKC", text).strip().lower()
    text = _WHITESPACE.sub(" ", text)
    return text.strip(" .,-_")
