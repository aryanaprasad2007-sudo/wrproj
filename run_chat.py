#!/usr/bin/env python3
"""Entry point for the persona tuning chat.

    python run_chat.py                    # persona/rei.yaml
    python run_chat.py persona/other.yaml
"""

import asyncio
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # optional dependency
    pass

from assistant import Chat
from assistant.persona import DEFAULT_PERSONA


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in.")
        return 1

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PERSONA
    if not path.exists():
        print(f"No persona file at {path}")
        return 1

    asyncio.run(Chat(path).run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
