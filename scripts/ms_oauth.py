"""One-time Microsoft Graph OAuth dance via device-code flow.

Prereqs:
  1. Created an Azure AD App Registration (see src/email_outlook.py header).
  2. MS_GRAPH_CLIENT_ID set in .env to the Application (client) ID.
  3. App marked as a public client (Authentication -> "Allow public client flows" = Yes).
  4. Mail.Send delegated permission added.

Usage:
    python -m scripts.ms_oauth

The script prints a short code + a URL. Open the URL on any device, enter the
code, sign in to the Microsoft account that will be the bot sender, and grant
Mail.Send. The cached token is written to credentials/ms_token.json and
reused by the bot.
"""
from __future__ import annotations

import sys

from src import config, email_outlook


def main() -> int:
    print(f"Microsoft Graph sender: {config.MS_GRAPH_SENDER}")
    print(f"Tenant:                  {config.MS_GRAPH_TENANT_ID}")
    print(f"Client ID:               {config.MS_GRAPH_CLIENT_ID}")
    print(f"Token will be cached at: {config.MS_GRAPH_TOKEN_PATH}")
    print()
    if not config.MS_GRAPH_CLIENT_ID:
        print("ERROR: MS_GRAPH_CLIENT_ID is not set in .env.")
        return 1

    token = email_outlook.acquire_token(interactive=True)
    print()
    print(f"OK — got access token (first 20 chars): {token[:20]}…")
    print(f"Cached at: {config.MS_GRAPH_TOKEN_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
