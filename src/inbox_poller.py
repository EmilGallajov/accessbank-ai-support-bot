"""Poll the bot's Gmail inbox for dept replies and update case status automatically.

This is the piece that closes the lifecycle loop:
    bot escalates → dept replies → poller detects → SQLite update → user notified.

Replies are matched to cases by the [AB-YYYY-NNNN] tag in the subject line.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Awaitable, Callable

from . import cases, config, departments, email_gmail, llm, security

NotifyCallable = Callable[[str, str], Awaitable[None]]
"""Async callback (telegram_user_id, message_text) -> None. Sends a message to the user."""

CASE_ID_RE = re.compile(r"\bAB-\d{4}-\d{4}\b")

CLASSIFIER_SYSTEM = """You read a customer-support email reply from one of AccessBank's internal departments. The original case is provided for context.

Classify the reply into ONE of:
- resolved: the team has solved the problem and given an answer/resolution
- pending: the team is investigating, asking us for more info, or otherwise not yet done
- needs_info: the team requires additional information from the customer
- unknown: the reply is unrelated, automated bounce, or unclear

OUTPUT ONLY a JSON object:
{
  "status": "resolved | pending | needs_info | unknown",
  "summary": "one-sentence customer-facing summary of the reply (in the original case's language)",
  "rationale": "one sentence"
}"""


def classify_reply(*, case_row: dict[str, Any], reply_body: str) -> dict[str, Any]:
    payload = (
        f"Original case ({case_row['case_id']}):\n"
        f"Department: {case_row['department']}\n"
        f"Language: {case_row.get('language', 'en')}\n"
        f"Issue summary: {case_row['issue_summary']}\n\n"
        f"Department's reply:\n---\n{reply_body[:3000]}\n---"
    )
    parsed = llm.chat_json(
        system=CLASSIFIER_SYSTEM,
        user=payload,
        temperature=0.1,
        max_tokens=300,
    )
    if "_parse_error" in parsed:
        return {"status": "unknown", "summary": reply_body[:200], "rationale": "parse_error"}
    return parsed


STATUS_MAP = {
    "resolved": "resolved",
    "pending": "pending",
    "needs_info": "pending",
    "unknown": None,
}


def _format_user_message(case_row: dict[str, Any], classification: dict[str, Any]) -> str:
    lang = case_row.get("language", "en")
    dept = departments.display_name(case_row["department"], lang)
    status = classification.get("status", "unknown")
    summary = classification.get("summary") or ""

    if status == "resolved":
        if lang == "az":
            return (
                f"✅ Müraciətiniz *{case_row['case_id']}* ({dept}) həll edildi:\n"
                f"_{summary}_\n\n"
                f"Müraciəti bağlamağa hazırsınızsa *YES* yazın. "
                f"Əgər problem davam edirsə, *NO* yazıb əlavə məlumatla cavab verin — "
                f"mən komandaya yenidən mesaj göndərəcəyəm."
            )
        return (
            f"✅ Your case *{case_row['case_id']}* ({dept}) has been resolved:\n"
            f"_{summary}_\n\n"
            f"Reply *YES* to close the ticket. If the problem is still happening, "
            f"reply *NO* with additional details and I'll forward your message back to the team."
        )

    if status in ("pending", "needs_info"):
        if lang == "az":
            return (
                f"ℹ️ Müraciətiniz *{case_row['case_id']}* ({dept}) üzərində işlənir:\n"
                f"_{summary}_\n\n"
                f"Komandaya əlavə cavab göndərmək istəyirsinizsə, mesajınızı yazın — "
                f"mən onu eyni e-poçt yazışmasında onlara çatdıracam."
            )
        return (
            f"ℹ️ Update on your case *{case_row['case_id']}* ({dept}):\n"
            f"_{summary}_\n\n"
            f"If you want to respond to the team, just type your reply here and "
            f"I'll forward it back to them in the same email thread."
        )

    return ""


async def _process_one(message_id: str, notify: NotifyCallable) -> None:
    try:
        msg = email_gmail.get_message(message_id)
    except Exception as exc:
        security.audit("poll_get_message_failed", message_id=message_id, error=str(exc))
        return

    headers = email_gmail.extract_headers(msg)
    subject = headers.get("subject", "")
    sender = headers.get("from", "")

    m = CASE_ID_RE.search(subject)
    if not m:
        # Not one of our threads — leave it untouched (don't mark as read).
        return

    case_id = m.group(0)
    case_row = cases.get_case(case_id)
    if case_row is None:
        security.audit("poll_unknown_case", case_id=case_id, message_id=message_id)
        try:
            email_gmail.mark_read(message_id)
        except Exception:
            pass
        return

    # Only treat as a team reply if it's NOT from the bot itself.
    if config.GMAIL_SENDER.lower() in sender.lower():
        try:
            email_gmail.mark_read(message_id)
        except Exception:
            pass
        return

    body = email_gmail.extract_text_body(msg)
    classification = classify_reply(case_row=case_row, reply_body=body)
    new_status_key = classification.get("status", "unknown")
    target_status = STATUS_MAP.get(new_status_key)
    summary = classification.get("summary") or ""

    security.audit(
        "poll_reply_classified",
        case_id=case_id,
        from_addr=sender,
        new_status=new_status_key,
        summary=summary[:200],
    )

    cases.add_history(
        case_id,
        source="email_reply",
        action="email_reply_received",
        note=f"From {sender}: {summary[:300]}",
    )

    if target_status is not None and target_status != case_row["status"]:
        cases.update_status(
            case_id,
            new_status=target_status,
            source="email_reply",
            note=summary,
            resolution=summary if target_status == "resolved" else None,
        )

    # Put the user in the appropriate post-reply conversational stage so the
    # bot's next handler knows how to interpret their next message.
    new_stage: str | None = None
    if target_status == "resolved":
        new_stage = "awaiting_resolution_decision"
    elif target_status == "pending":
        new_stage = "awaiting_user_followup_to_team"

    if new_stage:
        cases.set_pending(
            case_row["user_id"],
            {
                "stage": new_stage,
                "case_id": case_id,
                "language": case_row.get("language", "en"),
                "team_message_id": message_id,
            },
        )

    user_msg = _format_user_message(case_row, classification)
    if user_msg:
        try:
            await notify(case_row["user_id"], user_msg)
        except Exception as exc:
            security.audit(
                "poll_notify_failed",
                case_id=case_id,
                user_id=case_row["user_id"],
                error=str(exc),
            )

    try:
        email_gmail.mark_read(message_id)
    except Exception as exc:
        security.audit("poll_mark_read_failed", message_id=message_id, error=str(exc))


async def poll_once(notify: NotifyCallable) -> int:
    """Process all currently-unread messages. Returns number of dept replies handled."""
    try:
        unread = email_gmail.list_unread(max_results=25)
    except Exception as exc:
        security.audit("poll_list_failed", error=str(exc))
        return 0

    handled = 0
    for item in unread:
        msg_id = item.get("id")
        if not msg_id:
            continue
        try:
            await _process_one(msg_id, notify)
            handled += 1
        except Exception as exc:
            security.audit("poll_process_error", message_id=msg_id, error=str(exc))
    return handled


async def run_forever(notify: NotifyCallable) -> None:
    """Background task: poll every INBOX_POLL_INTERVAL_SECONDS forever."""
    interval = config.INBOX_POLL_INTERVAL_SECONDS
    print(f"[inbox_poller] starting, interval={interval}s")
    while True:
        try:
            n = await poll_once(notify)
            if n:
                print(f"[inbox_poller] processed {n} unread messages")
        except Exception as exc:
            security.audit("poll_loop_error", error=str(exc))
            print(f"[inbox_poller] error: {exc}")
        await asyncio.sleep(interval)
