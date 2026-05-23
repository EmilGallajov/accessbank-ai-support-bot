"""Gmail API send + read. OAuth2-based, NOT SMTP (satisfies spec anti-rule #4)."""
from __future__ import annotations

import base64
import json
import mimetypes
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Iterable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from . import config

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

_service: Any = None


def _load_creds() -> Credentials:
    token_path: Path = config.GMAIL_TOKEN_PATH
    cred_path: Path = config.GMAIL_CREDENTIALS_PATH

    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not cred_path.exists():
                raise RuntimeError(
                    f"Missing {cred_path}. Download an OAuth Desktop client JSON from "
                    f"Google Cloud Console -> APIs & Services -> Credentials, save it there, "
                    f"then run `python -m scripts.gmail_oauth`."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
    return creds


def service() -> Any:
    global _service
    if _service is None:
        creds = _load_creds()
        _service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return _service


def send_escalation(
    *,
    to_addr: str,
    subject: str,
    body: str,
    attachments: Iterable[str | Path] | None = None,
) -> dict[str, str]:
    """Send an email from the bot sender to a department mailbox.

    If `attachments` is provided (list of filesystem paths), the email is sent
    as multipart/mixed with each file attached. Otherwise a plain text/plain
    message is sent. Returns dict with `message_id` and `thread_id`.
    """
    attachment_paths: list[Path] = [Path(p) for p in (attachments or []) if p]
    attachment_paths = [p for p in attachment_paths if p.exists()]

    if attachment_paths:
        msg = MIMEMultipart()
        msg["To"] = to_addr
        msg["From"] = config.GMAIL_SENDER
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        for path in attachment_paths:
            ctype, encoding = mimetypes.guess_type(str(path))
            if ctype is None or encoding is not None:
                ctype = "application/octet-stream"
            maintype, subtype = ctype.split("/", 1)
            with path.open("rb") as fh:
                data = fh.read()
            part = MIMEBase(maintype, subtype)
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{path.name}"',
            )
            msg.attach(part)
    else:
        msg = MIMEText(body, _charset="utf-8")
        msg["To"] = to_addr
        msg["From"] = config.GMAIL_SENDER
        msg["Subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = service().users().messages().send(
        userId="me",
        body={"raw": raw},
    ).execute()
    return {"message_id": sent.get("id", ""), "thread_id": sent.get("threadId", "")}


def send_reply(
    *,
    to_addr: str,
    subject: str,
    body: str,
    thread_id: str,
    in_reply_to_message_id: str | None = None,
) -> dict[str, str]:
    """Send an email that Gmail will group into an existing thread.

    Pass `thread_id` (the case's stored email_thread_id) so the message lands
    in the same conversation. If `in_reply_to_message_id` is given (e.g. the
    Gmail header `Message-ID` of the dept's last reply, retrieved via
    inbox_poller), it's added as the In-Reply-To/References headers so mail
    clients render the reply nicely.
    """
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject

    msg = MIMEText(body, _charset="utf-8")
    msg["To"] = to_addr
    msg["From"] = config.GMAIL_SENDER
    msg["Subject"] = subject
    if in_reply_to_message_id:
        msg["In-Reply-To"] = in_reply_to_message_id
        msg["References"] = in_reply_to_message_id

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = service().users().messages().send(
        userId="me",
        body={"raw": raw, "threadId": thread_id},
    ).execute()
    return {"message_id": sent.get("id", ""), "thread_id": sent.get("threadId", "")}


# ----------------------------------------------------------------------------
# Inbox read API (used by inbox_poller.py)
# ----------------------------------------------------------------------------


def list_unread(*, max_results: int = 25) -> list[dict[str, Any]]:
    """Return summary metadata for unread messages in the bot sender's inbox."""
    resp = service().users().messages().list(
        userId="me",
        q="is:unread in:inbox",
        maxResults=max_results,
    ).execute()
    return resp.get("messages", []) or []


def get_message(message_id: str) -> dict[str, Any]:
    return service().users().messages().get(
        userId="me",
        id=message_id,
        format="full",
    ).execute()


def mark_read(message_id: str) -> None:
    service().users().messages().modify(
        userId="me",
        id=message_id,
        body={"removeLabelIds": ["UNREAD"]},
    ).execute()


def extract_headers(msg: dict[str, Any]) -> dict[str, str]:
    headers = msg.get("payload", {}).get("headers", []) or []
    return {h["name"].lower(): h["value"] for h in headers if "name" in h and "value" in h}


def extract_text_body(msg: dict[str, Any]) -> str:
    """Recursively walk MIME parts to pull a plain-text body."""

    def _walk(part: dict[str, Any]) -> str:
        mime_type = part.get("mimeType", "")
        body = part.get("body", {}) or {}
        data = body.get("data")
        if data and mime_type.startswith("text/"):
            try:
                decoded = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
                return decoded
            except Exception:
                return ""
        for sub in part.get("parts", []) or []:
            txt = _walk(sub)
            if txt:
                return txt
        return ""

    payload = msg.get("payload", {}) or {}
    text = _walk(payload)
    if text:
        # Strip the most common quoted-original-block markers.
        for marker in ("On ", "-----Original Message-----", "________________________________"):
            idx = text.find(marker)
            if idx > 50:
                text = text[:idx]
                break
    return text.strip()
