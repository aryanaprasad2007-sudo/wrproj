#!/usr/bin/env python3
"""Run the Telegram bot.

    python run_telegram.py

Needs the service (run_server.py) up. Talks to it over HTTP, so it can run on a
different machine — set ASSISTANT_URL if it does.
"""

import asyncio
import logging
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from assistant.telegram import from_env


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        bot = from_env()
    except RuntimeError as exc:
        print(exc)
        return 1

    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
