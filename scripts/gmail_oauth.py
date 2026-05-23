"""One-time Gmail OAuth dance.

Prereqs:
  1. Created a Google Cloud project + enabled the Gmail API.
  2. Created an OAuth 2.0 Client ID (Application type: Desktop app).
  3. Downloaded the credentials JSON and saved it to credentials/credentials.json.
  4. Added the bot Gmail address as a Test User on the OAuth consent screen.

Usage:
  python -m scripts.gmail_oauth

This opens your browser, asks you to grant the requested scopes
(gmail.send + gmail.modify), and writes credentials/token.json with a
long-lived refresh token. After this runs once, the bot can send and read
email without further interaction.
"""
from __future__ import annotations

import sys

from src import config, email_gmail


def main() -> int:
    print(f"Bot sender Gmail: {config.GMAIL_SENDER}")
    print(f"Credentials path: {config.GMAIL_CREDENTIALS_PATH}")
    print(f"Token will be written to: {config.GMAIL_TOKEN_PATH}")
    print()
    print("Forcing OAuth flow — your browser should open in a moment...")
    print()

    # Touch the service so the OAuth dance runs and token.json is written.
    svc = email_gmail.service()
    profile = svc.users().getProfile(userId="me").execute()
    print()
    print("OK — authenticated as:", profile.get("emailAddress"))
    print(f"  messagesTotal: {profile.get('messagesTotal')}")
    print(f"  threadsTotal:  {profile.get('threadsTotal')}")
    print(f"  Token saved to: {config.GMAIL_TOKEN_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
