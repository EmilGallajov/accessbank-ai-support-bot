"""The 5 escalation departments. Keys are used as enums across the codebase."""
from __future__ import annotations

DEPARTMENTS: dict[str, dict[str, str]] = {
    "digital_banking": {
        "name_en": "Digital Banking",
        "name_az": "Rəqəmsal Bankçılıq",
        "responsibility": "Mobile app, internet banking, login, OTP, technical access issues.",
        "examples": "Cannot log in to mobile app. App crashes. OTP not received. Internet banking down.",
    },
    "card_ops": {
        "name_en": "Card Operations",
        "name_az": "Kart Əməliyyatları",
        "responsibility": "Card payments, blocked cards, failed card transactions, lost/stolen card.",
        "examples": "Card payment failed. Card was declined. Lost my card. Card blocked.",
    },
    "transfers": {
        "name_en": "Transfers & Payments",
        "name_az": "Köçürmələr və Ödənişlər",
        "responsibility": "Failed transfers, delayed payments, deducted amount, payment confirmation.",
        "examples": "Transfer failed but money deducted. Payment never arrived. Delayed transfer.",
    },
    "loans": {
        "name_en": "Loans & Applications",
        "name_az": "Kreditlər və Müraciətlər",
        "responsibility": "Loan applications, loan status, required documents, repayment questions.",
        "examples": "No response to my loan application. Repayment amount wrong. What documents do I need?",
    },
    "branch": {
        "name_en": "Customer Service / Branch Operations",
        "name_az": "Müştəri Xidməti / Filial Əməliyyatları",
        "responsibility": "General service complaints, branch experience, queue/service issues.",
        "examples": "Poor service at branch. Long queue. Branch staff was rude.",
    },
}

DEPT_KEYS = list(DEPARTMENTS.keys())


def display_name(key: str, lang: str = "en") -> str:
    if key not in DEPARTMENTS:
        return key
    return DEPARTMENTS[key]["name_az" if lang == "az" else "name_en"]


def router_prompt_block() -> str:
    """Compact description block used in the LLM classifier system prompt."""
    lines = []
    for key, info in DEPARTMENTS.items():
        lines.append(f"- {key}: {info['responsibility']} Examples: {info['examples']}")
    return "\n".join(lines)
