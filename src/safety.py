"""Redact sensitive banking data before storage or outbound email.

Two layers:
  1. The agent's system prompt forbids asking for PIN/CVV/password/OTP/full card #.
  2. This regex post-filter strips anything that slipped through, regardless of source.
"""
from __future__ import annotations

import re

# 13-19 consecutive digits (card #), possibly separated by spaces or dashes.
_CARD_NUMBER_RE = re.compile(r"(?:\d[ -]?){12,18}\d")

# 3-8 digit code mentioned within 10 chars of OTP / PIN / code / şifrə / kod / CVV.
_OTP_NEAR_RE = re.compile(
    r"""(?ix)
    (?:
      (?:otp|pin|code|cvv|cvc|kod|sifre|sifr|sifrem|sifremiz)
      [^\d\n]{0,10}\d{3,8}
      |
      \d{3,8}[^\d\n]{0,10}(?:otp|pin|code|cvv|cvc|kod|sifre|sifr|sifrem|sifremiz)
    )
    """
)

# Same idea but for Azerbaijani diacritics (şifrə, şifrəm). Separate regex because
# raw-string + verbose mode + diacritics interact awkwardly with the character classes.
_OTP_NEAR_AZ_RE = re.compile(
    r"(?:şifr[əe]m?|kod)\s*[:=]?\s*\d{3,8}|\d{3,8}\s*(?:şifr[əe]m?|kod)",
    re.IGNORECASE,
)

# Explicit "password is X" / "my pin is X" / "şifrəm: X" style phrases.
# IMPORTANT: we only redact when the trailing value looks like an actual
# password (contains a digit). Otherwise expressions like "my password is wrong"
# or "şifrəm doğrudur" — where the user is *talking about* a password without
# disclosing it — would be over-redacted and break the issue-reporting flow.
_PASSWORD_PHRASE_RE = re.compile(
    r"""(?ix)
    (?:my\ +(?:password|pin)|password\ +is|pin\ +is)
    \s*[:=]?\s*
    (?=\S*\d)               # require at least one digit in the value
    [A-Za-z0-9!@#$%^&*_\-]{3,}
    """
)

_PASSWORD_PHRASE_AZ_RE = re.compile(
    r"(?:şifr[əe]m|mənim\s+şifr[əe]m)\s*[:=]?\s*(?=\S*\d)[A-Za-z0-9!@#$%^&*_\-]{3,}",
    re.IGNORECASE,
)


def sanitize(text: str | None) -> str:
    """Return the input with card numbers, OTP-looking codes, and passwords redacted."""
    if not text:
        return ""

    out = text
    out = _CARD_NUMBER_RE.sub("[CARD-REDACTED]", out)
    out = _PASSWORD_PHRASE_RE.sub("[PASSWORD-REDACTED]", out)
    out = _PASSWORD_PHRASE_AZ_RE.sub("[PASSWORD-REDACTED]", out)
    out = _OTP_NEAR_RE.sub("[CODE-REDACTED]", out)
    out = _OTP_NEAR_AZ_RE.sub("[CODE-REDACTED]", out)
    return out


def contains_sensitive(text: str | None) -> bool:
    """Cheap check: does the input look like it contains sensitive data?"""
    if not text:
        return False
    return bool(
        _CARD_NUMBER_RE.search(text)
        or _OTP_NEAR_RE.search(text)
        or _OTP_NEAR_AZ_RE.search(text)
        or _PASSWORD_PHRASE_RE.search(text)
        or _PASSWORD_PHRASE_AZ_RE.search(text)
    )
