"""Lightweight, classifier-free language detection.

Used wherever we need to pick an EN vs AZ refusal/reply string *before* (or
without) involving the LLM classifier — e.g. preflight checks in
`security.py` and early refusals in `agent.py`. Kept in its own module so
both can import without circular dependencies.
"""
from __future__ import annotations

import re

# We INTENTIONALLY exclude `ı` / `I` from this character class. The dotless
# Azerbaijani `ı` (U+0131) case-folds to ASCII `i` under Unicode rules, so
# including it with IGNORECASE would flag every English message containing
# the letter `i`. The other diacritics (ş, ə, ç, ğ, ö, ü and their uppercase
# forms) are unique to AZ/TR and safe to match.
_AZ_DIACRITIC_RE = re.compile(r"[şəçğöüŞƏÇĞÖÜ]")

# Words that strongly signal Azerbaijani. Includes Latinized variants (no
# diacritics) — phone users routinely drop them.
_AZ_COMMON_WORDS_RE = re.compile(
    r"\b("
    # pronouns / possessives
    r"mənim|menim|sənin|senin|onun|bizim|sizin|mənə|mene|sənə|sene|"
    # nouns
    r"köçürmə|kocurme|kredit|kart|kartım|kartim|"
    r"hesab|hesabım|hesabim|filial|şöbə|sobe|"
    r"müraciət|muraciet|məbləğ|mebleg|"
    r"şifr[əe]|sifre|"
    r"nömrə|nomre|nömrəsi|nomresi|nömrəni|nomreni|"
    # verbs / auxiliaries
    r"daxil|ola|bilmir[əe]m|bilmirem|"
    r"bilərsən|bilersen|bilərsənmi|bilersenmi|bilirsən|bilirsen|"
    r"deyə|deye|deyirəm|deyirem|"
    r"olub|olmadı|olmadi|oldu|"
    # question words / modifiers
    r"necə|nece|harada|harda|niyə|niye|hansı|hansi|"
    r"nə\s+vaxt|ne\s+vaxt|nə\s+üçün|ne\s+ucun|"
    r"bütün|butun|lazım|lazim|"
    # politeness / help / acknowledgements (diacritic + latinized)
    r"zəhmət|zehmet|zəhmət\s+olmasa|zehmet\s+olmasa|"
    r"kömək|komek|kömək\s+et|komek\s+et|yardım|yardim|"
    r"təşəkkür|tesekkur|təşəkkürlər|tesekkurler|sağ\s+ol|sag\s+ol|"
    r"lütfən|lutfen|"
    r"bəli|beli|xeyr|yox|tamam|yaxşı|yaxsi|"
    r"anlamadım|anlamadim|anladım|anladim|başa\s+düşmədim|basa\s+dusmedim|"
    # misc
    r"problem|xahiş|xahis|göstər|goster|icra"
    r")\b",
    re.IGNORECASE,
)

# Azerbaijani agglutinative suffixes that essentially never appear at the
# end of English words. Catches Latinized AZ not in the common-words list
# (e.g. "userlerin", "kartlarini").
_AZ_SUFFIX_RE = re.compile(
    r"\b\w+(?:lərin|lerin|ların|larin|lərini|lerini|larını|larini)\b",
    re.IGNORECASE,
)


def looks_like_azerbaijani(text: str) -> bool:
    """Best-effort AZ detection. Returns True if `text` shows AZ markers
    (diacritics, common AZ words, or AZ suffixes — including Latinized
    forms)."""
    if not text:
        return False
    return bool(
        _AZ_DIACRITIC_RE.search(text)
        or _AZ_COMMON_WORDS_RE.search(text)
        or _AZ_SUFFIX_RE.search(text)
    )


def pick(text: str, *, en: str, az: str) -> str:
    """Convenience: return `az` if the message looks Azerbaijani, else `en`."""
    return az if looks_like_azerbaijani(text) else en
