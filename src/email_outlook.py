"""Microsoft Graph email sender (alternative to Gmail).

Uses MSAL device-code flow with a public client app to obtain an OAuth token,
then calls the Graph `me/sendMail` endpoint. Just like the Gmail path, this is
an authenticated API call (NOT SMTP).

Set EMAIL_PROVIDER=outlook in .env to use this instead of Gmail.

Required Azure AD App Registration setup:
  1. Go to https://entra.microsoft.com/ (or portal.azure.com -> Microsoft Entra ID).
  2. App registrations -> New registration:
       Name: "AccessBank Demo Bot"
       Supported account types: "Accounts in any organizational directory and personal Microsoft accounts"
       Redirect URI: (leave empty for now)
  3. After creation, copy the "Application (client) ID" -> MS_GRAPH_CLIENT_ID in .env.
  4. Authentication -> "Allow public client flows" -> Yes -> Save.
  5. API permissions -> Add a permission -> Microsoft Graph -> Delegated:
       Mail.Send  (+ Mail.ReadWrite if you also want inbox polling via Outlook)
     -> Grant admin consent (or accept on first sign-in).
  6. Run `python -m scripts.ms_oauth` and follow the device-code prompt.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import msal
import requests

from . import config

SCOPES = ["Mail.Send"]
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    p: Path = config.MS_GRAPH_TOKEN_PATH
    if p.exists():
        cache.deserialize(p.read_text())
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        p: Path = config.MS_GRAPH_TOKEN_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(cache.serialize())


def _app(cache: msal.SerializableTokenCache) -> msal.PublicClientApplication:
    if not config.MS_GRAPH_CLIENT_ID:
        raise RuntimeError(
            "MS_GRAPH_CLIENT_ID is not configured in .env. "
            "Register an Azure AD app and copy the Application (client) ID."
        )
    authority = f"https://login.microsoftonline.com/{config.MS_GRAPH_TENANT_ID or 'common'}"
    return msal.PublicClientApplication(
        client_id=config.MS_GRAPH_CLIENT_ID,
        authority=authority,
        token_cache=cache,
    )


def acquire_token(interactive: bool = False) -> str:
    """Return a usable access token. If no cached token exists and interactive=True,
    triggers the device-code flow (prints a code + URL to the console)."""
    cache = _cache()
    app = _app(cache)

    accounts = app.get_accounts()
    result: dict[str, Any] | None = None
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    if not result or "access_token" not in result:
        if not interactive:
            raise RuntimeError(
                "No cached Microsoft token. Run `python -m scripts.ms_oauth` once to authenticate."
            )
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Failed to initiate device flow: {flow}")
        print(flow["message"])
        result = app.acquire_token_by_device_flow(flow)

    _save_cache(cache)
    if "access_token" not in result:
        raise RuntimeError(f"Failed to obtain Microsoft Graph token: {result}")
    return result["access_token"]


def send_escalation(
    *,
    to_addr: str,
    subject: str,
    body: str,
    attachments: "list[str | __import__('pathlib').Path] | None" = None,
) -> dict[str, str]:
    """Send an email via Microsoft Graph. Attachments (filesystem paths) are
    base64-encoded inline per Graph's fileAttachment schema. Returns
    {message_id, thread_id} (both synthetic since sendMail returns 202)."""
    import base64 as _b64
    import mimetypes
    from pathlib import Path as _Path

    token = acquire_token(interactive=False)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    file_attachments: list[dict[str, Any]] = []
    for raw_path in attachments or []:
        if not raw_path:
            continue
        path = _Path(raw_path)
        if not path.exists():
            continue
        ctype, _ = mimetypes.guess_type(str(path))
        ctype = ctype or "application/octet-stream"
        with path.open("rb") as fh:
            encoded = _b64.b64encode(fh.read()).decode("ascii")
        file_attachments.append({
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": path.name,
            "contentType": ctype,
            "contentBytes": encoded,
        })

    message: dict[str, Any] = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": to_addr}}],
    }
    if file_attachments:
        message["attachments"] = file_attachments

    payload = {"message": message, "saveToSentItems": True}
    resp = requests.post(
        f"{GRAPH_BASE}/me/sendMail",
        headers=headers,
        json=payload,
        timeout=30,
    )
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Graph sendMail failed {resp.status_code}: {resp.text}")

    import hashlib
    synth_id = "ms-" + hashlib.sha1(subject.encode("utf-8")).hexdigest()[:12]
    return {"message_id": synth_id, "thread_id": synth_id}


def send_reply(
    *,
    to_addr: str,
    subject: str,
    body: str,
    thread_id: str,
    in_reply_to_message_id: str | None = None,
) -> dict[str, str]:
    """Microsoft Graph 'reply' equivalent. For simplicity we just call sendMail
    with a Re: subject — Outlook clients will still group by conversation."""
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject
    return send_escalation(to_addr=to_addr, subject=subject, body=body)
