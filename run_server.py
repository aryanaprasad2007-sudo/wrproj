#!/usr/bin/env python3
"""Run the assistant service.

    python run_server.py

Binds to 127.0.0.1 by default. Set ASSISTANT_HOST=0.0.0.0 only if you know what
is between this process and the internet — the bearer token is the only thing
guarding your API spend.
"""

import os
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import uvicorn

from assistant.server import create_app


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in.")
        return 1

    host = os.environ.get("ASSISTANT_HOST", "127.0.0.1")
    port = int(os.environ.get("ASSISTANT_PORT", "8000"))

    try:
        app = create_app()
    except RuntimeError as exc:
        print(exc)
        return 1

    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"warning: binding to {host} — this service is reachable off-box.")

    uvicorn.run(app, host=host, port=port, log_level=os.environ.get("LOG_LEVEL", "info"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
