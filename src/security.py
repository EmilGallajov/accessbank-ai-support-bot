"""Prompt-injection defense, scope guard, rate limiting, and audit logging.

Maps to AI-agent security controls #3, #4, #5, #6, #10, #11 from the project plan.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

# ----------------------------------------------------------------------------
# Layer 1 — Regex pattern blocking (no LLM cost)
# ----------------------------------------------------------------------------

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bignore\s+(?:(?:all|previous|above|prior|my|your|the)\s+)*(?:instructions?|prompts?|rules?|directives?)", re.IGNORECASE),
    re.compile(r"\bdisregard\s+(?:your|the|previous|prior|all)\b", re.IGNORECASE),
    re.compile(r"\byou\s+are\s+(?:now|actually)\s+(?:a|an)\s+", re.IGNORECASE),
    re.compile(r"\bsystem\s+prompt\b", re.IGNORECASE),
    re.compile(r"\breveal\s+(?:your|the)\s+(?:instructions?|prompt|rules?|system)", re.IGNORECASE),
    re.compile(r"\b(?:DAN|developer)\s+mode\b", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
    re.compile(r"\[/?INST\]", re.IGNORECASE),
    re.compile(r"<\|[^|]+\|>"),
    re.compile(r"\b(?:os\.system|subprocess|eval\(|exec\()", re.IGNORECASE),
    re.compile(r"\bprint\s+(?:your|the)\s+(?:system|hidden)\b", re.IGNORECASE),
    re.compile(r"\boverride\s+(?:your|the)\s+(?:role|persona|instructions?)", re.IGNORECASE),
    re.compile(r"\bact\s+as\s+(?:a|an|the)\s+(?!.*(?:bank|customer|support|accessbank))", re.IGNORECASE),
    # Azerbaijani
    re.compile(r"əvvəlki\s+(?:t[əa]limatları|göstərişlər)", re.IGNORECASE),
    re.compile(r"sən\s+(?:indi|artıq)\s+", re.IGNORECASE),
]


def regex_injection_detected(text: str) -> str | None:
    """Return a matched-pattern preview if input looks like injection, else None."""
    if not text:
        return None
    for pat in _INJECTION_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(0)[:80]
    return None


# ----------------------------------------------------------------------------
# Layer 3 — Output validation (post-LLM, pre-send)
# ----------------------------------------------------------------------------

_OUTPUT_LEAK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"my\s+(?:system\s+)?(?:prompt|instructions?)\s+(?:is|are|says?)", re.IGNORECASE),
    re.compile(r"i\s+was\s+(?:told|instructed|programmed)\s+to", re.IGNORECASE),
    re.compile(r"the\s+(?:system\s+)?prompt\s+(?:is|says?|contains?)", re.IGNORECASE),
    re.compile(r"```\s*(?:python|javascript|bash|sh|sql)", re.IGNORECASE),
]

_MAX_OUTPUT_CHARS = 2000


def validate_output(text: str) -> str:
    """Sanitize an LLM-generated reply before it leaves the system."""
    if not text:
        return ""

    # Reject responses that look like system-prompt leaks.
    for pat in _OUTPUT_LEAK_PATTERNS:
        if pat.search(text):
            return (
                "Sorry — I can only help with AccessBank customer support questions. "
                "How can I help you with your banking needs?"
            )

    if len(text) > _MAX_OUTPUT_CHARS:
        text = text[: _MAX_OUTPUT_CHARS - 1] + "…"

    return text


# ----------------------------------------------------------------------------
# Rate limiting (Behavioral Monitoring control #10)
# ----------------------------------------------------------------------------

_user_msg_times: dict[str, deque[float]] = defaultdict(deque)


def rate_limited(user_id: str) -> bool:
    """Return True if the user has exceeded the rate limit (and update the window)."""
    now = time.time()
    window_start = now - config.RATE_LIMIT_WINDOW_SECONDS
    dq = _user_msg_times[user_id]
    while dq and dq[0] < window_start:
        dq.popleft()
    if len(dq) >= config.RATE_LIMIT_MAX_MSGS:
        return True
    dq.append(now)
    return False


# ----------------------------------------------------------------------------
# Audit logging
# ----------------------------------------------------------------------------

_logger = logging.getLogger("audit")
_logger.setLevel(logging.INFO)
if not _logger.handlers:
    Path(config.AUDIT_LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(config.AUDIT_LOG_PATH, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)
    _logger.propagate = False


def audit(event: str, **fields: Any) -> None:
    """Append a one-line JSON audit record to data/audit.log."""
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
    }
    record.update(fields)
    try:
        _logger.info(json.dumps(record, ensure_ascii=False, default=str))
    except Exception:  # never let logging crash the agent
        pass


# ----------------------------------------------------------------------------
# Preflight (called at the top of every user message handler)
# ----------------------------------------------------------------------------


@dataclass
class PreflightResult:
    ok: bool
    block_reason: str | None = None  # "rate_limit" | "injection_detected" | None
    refusal_message: str | None = None


def preflight(user_id: str, text: str) -> PreflightResult:
    """Run all input-side checks. Returns ok=True if the message may proceed."""
    text = (text or "").strip()
    audit("input", user_id=user_id, text=text[:500])

    if rate_limited(user_id):
        audit("rate_limited", user_id=user_id)
        return PreflightResult(
            ok=False,
            block_reason="rate_limit",
            refusal_message=(
                "You've sent quite a few messages in a short time. "
                "Please wait a moment before sending another."
            ),
        )

    inj = regex_injection_detected(text)
    if inj:
        audit("injection_blocked_layer1", user_id=user_id, match=inj)
        return PreflightResult(
            ok=False,
            block_reason="injection_detected",
            refusal_message=(
                "I'm here to help with AccessBank customer support only. "
                "I can't follow that kind of instruction — please ask me a banking question."
            ),
        )

    return PreflightResult(ok=True)
