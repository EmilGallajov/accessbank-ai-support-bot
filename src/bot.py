"""Telegram bot — the user-facing surface.

The bot has exactly one role: relay user messages to `agent.handle` and render
the response (including the inline YES/NO confirmation flow for escalations).

Status updates are NOT driven by admin commands. They flow naturally from
`inbox_poller.py` -> notify(user_id, text) -> Telegram message.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import agent, config, security


ATTACHMENT_DIR = config.PROJECT_ROOT / "data" / "attachments"
ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)


# Module-level app reference, set in build_app(), used by `notify_user_callback`.
_app: Application | None = None


async def _start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "👋 Hi! I'm AccessBank's AI customer-support assistant.\n\n"
        "• Ask me anything about AccessBank (working hours, products, branches, app).\n"
        "• If you have a problem, describe it and I'll open a case with the right department.\n"
        "• Type /status to see your cases.\n\n"
        "I won't ever ask for your PIN, CVV, password, OTP, or full card number — "
        "and please don't share them."
    )
    await update.effective_message.reply_text(msg)


async def _help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _start(update, context)


async def _status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return
    resp = agent.handle(str(user.id), user.full_name, "what are my cases?")
    await update.effective_message.reply_text(resp.text)


async def _download_photos(message: Any, context: ContextTypes.DEFAULT_TYPE, user_id: str) -> list[str]:
    """Download the highest-res version of any photos on this message.
    Returns absolute filesystem paths to the saved jpegs."""
    if not message.photo:
        return []
    photo = message.photo[-1]  # highest resolution
    file = await context.bot.get_file(photo.file_id)
    user_dir = ATTACHMENT_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{int(time.time())}_{uuid.uuid4().hex[:8]}.jpg"
    path = user_dir / fname
    await file.download_to_drive(custom_path=str(path))
    return [str(path)]


async def _dispatch(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    attachment_paths: list[str] | None = None,
) -> None:
    """Shared dispatch logic for text + photo handlers."""
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    user_id = str(user.id)
    user_name = user.full_name

    try:
        await context.bot.send_chat_action(chat_id=message.chat_id, action="typing")
    except Exception:
        pass

    loop = asyncio.get_running_loop()
    try:
        resp = await loop.run_in_executor(
            None,
            lambda: agent.handle(user_id, user_name, text, attachment_paths=attachment_paths),
        )
    except Exception as exc:
        security.audit("agent_handle_error", user_id=user_id, error=str(exc))
        await message.reply_text(
            "Sorry, I hit an unexpected error. Please try again in a moment."
        )
        return

    reply_text = resp.text or ""
    try:
        await message.reply_text(reply_text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await message.reply_text(reply_text)


async def _on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return
    await _dispatch(update, context, message.text.strip(), attachment_paths=None)


async def _on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a Telegram photo (with optional caption) by downloading the image
    and forwarding both the caption (as text) and the local file path to the
    agent. The agent merges it into the user's pending case draft."""
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    user_id = str(user.id)
    try:
        paths = await _download_photos(message, context, user_id)
    except Exception as exc:
        security.audit("photo_download_failed", user_id=user_id, error=str(exc))
        await message.reply_text(
            "I couldn't download that photo. Could you try sending it again?"
        )
        return

    caption = (message.caption or "").strip()
    await _dispatch(update, context, caption, attachment_paths=paths)


async def notify_user_callback(user_id: str, text: str) -> None:
    """Async callback for the inbox poller to push messages to a Telegram user."""
    if _app is None:
        return
    try:
        await _app.bot.send_message(
            chat_id=int(user_id),
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as exc:
        # Fall back to plain text if Markdown breaks; if even that fails, swallow.
        try:
            await _app.bot.send_message(chat_id=int(user_id), text=text)
        except Exception:
            security.audit(
                "telegram_notify_failed",
                user_id=user_id,
                error=str(exc),
            )


def build_app() -> Application:
    global _app
    _app = (
        ApplicationBuilder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .build()
    )
    _app.add_handler(CommandHandler("start", _start))
    _app.add_handler(CommandHandler("help", _help))
    _app.add_handler(CommandHandler("status", _status))
    _app.add_handler(MessageHandler(filters.PHOTO, _on_photo))
    _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))
    return _app
