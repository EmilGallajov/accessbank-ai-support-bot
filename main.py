"""Entrypoint — start the Telegram bot AND the Gmail inbox poller concurrently."""
from __future__ import annotations

import asyncio
import logging

from src import bot, cases, inbox_poller


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # The Telegram lib is chatty at DEBUG; keep it at WARNING to make our logs readable.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


async def _amain() -> None:
    _setup_logging()
    cases.init()

    application = bot.build_app()

    # Start the inbox poller as a background task on the same event loop.
    poller_task = asyncio.create_task(
        inbox_poller.run_forever(bot.notify_user_callback)
    )

    print("AccessBank support bot is running. Send a Telegram message to test.")
    print("Inbox poller is running in the background (checking dept replies).")

    try:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        # Park until cancelled (Ctrl+C).
        await asyncio.Event().wait()
    finally:
        poller_task.cancel()
        try:
            await application.updater.stop()
        except Exception:
            pass
        try:
            await application.stop()
        except Exception:
            pass
        try:
            await application.shutdown()
        except Exception:
            pass


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
