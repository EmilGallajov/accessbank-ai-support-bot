"""Centralised environment + path configuration."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")


_PLACEHOLDER_PREFIXES = ("REPLACE_ME", "PLACEHOLDER")


def _env(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(name, default)
    if required and (
        val is None
        or val == ""
        or any(val.startswith(p) for p in _PLACEHOLDER_PREFIXES)
    ):
        raise RuntimeError(
            f"Missing required environment variable {name}. "
            f"Copy .env.example to .env and fill in real values."
        )
    return val or ""


# --- OpenAI ---
OPENAI_API_KEY = _env("OPENAI_API_KEY", required=True)
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_EMBED_MODEL = _env("OPENAI_EMBED_MODEL", "text-embedding-3-small")

# --- Telegram ---
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN", required=True)

# --- Gmail ---
GMAIL_SENDER = _env("GMAIL_SENDER", required=True)
GMAIL_CREDENTIALS_PATH = PROJECT_ROOT / _env("GMAIL_CREDENTIALS_PATH", "credentials/credentials.json")
GMAIL_TOKEN_PATH = PROJECT_ROOT / _env("GMAIL_TOKEN_PATH", "credentials/token.json")

# --- Department mailboxes ---
DEPT_EMAILS: dict[str, str] = {
    "digital_banking": _env("DEPT_DIGITAL_EMAIL", required=True),
    "card_ops": _env("DEPT_CARDS_EMAIL", required=True),
    "transfers": _env("DEPT_TRANSFERS_EMAIL", required=True),
    "loans": _env("DEPT_LOANS_EMAIL", required=True),
    "branch": _env("DEPT_BRANCH_EMAIL", required=True),
}

# --- Paths ---
CASES_DB_PATH = PROJECT_ROOT / _env("CASES_DB_PATH", "data/cases.db")
CHROMA_PATH = PROJECT_ROOT / _env("CHROMA_PATH", "data/chroma")
AUDIT_LOG_PATH = PROJECT_ROOT / _env("AUDIT_LOG_PATH", "data/audit.log")
KNOWLEDGE_DIR = PROJECT_ROOT / _env("KNOWLEDGE_DIR", "knowledge")

# --- Email provider selection ---
EMAIL_PROVIDER = _env("EMAIL_PROVIDER", "gmail").lower().strip()

# --- Microsoft Graph ---
MS_GRAPH_CLIENT_ID = _env("MS_GRAPH_CLIENT_ID", "")
MS_GRAPH_TENANT_ID = _env("MS_GRAPH_TENANT_ID", "common")
MS_GRAPH_SENDER = _env("MS_GRAPH_SENDER", "")
MS_GRAPH_TOKEN_PATH = PROJECT_ROOT / _env("MS_GRAPH_TOKEN_PATH", "credentials/ms_token.json")

# --- Behavior tuning ---
INBOX_POLL_INTERVAL_SECONDS = int(_env("INBOX_POLL_INTERVAL_SECONDS", "30"))
RATE_LIMIT_MAX_MSGS = int(_env("RATE_LIMIT_MAX_MSGS", "20"))
RATE_LIMIT_WINDOW_SECONDS = int(_env("RATE_LIMIT_WINDOW_SECONDS", "300"))
KB_TOP_K = int(_env("KB_TOP_K", "3"))

# Ensure data dirs exist at import time (cheap, idempotent).
for p in [CASES_DB_PATH.parent, CHROMA_PATH, AUDIT_LOG_PATH.parent, KNOWLEDGE_DIR]:
    p.mkdir(parents=True, exist_ok=True)
