#!/usr/bin/env python3
"""Everything in one terminal: the brain, a client, and her face.

    python run_all.py              talk out loud if you have a mic, else type
    python run_all.py --voice      force the typed client
    python run_all.py --listen     force the spoken client
    python run_all.py --port 8123

The service runs inside this process rather than beside it, so there's one
thing to start and one thing to Ctrl-C. `run_server.py` is still the right way
to run it for real — this is for sitting down and trying it.
"""

import argparse
import asyncio
import os
import sys
import webbrowser

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def _port_is_free(port: int) -> bool:
    """Checked before starting uvicorn rather than after it fails.

    uvicorn calls sys.exit() when it can't bind, and asyncio re-raises a
    SystemExit from a task straight into the event loop — past whoever is
    awaiting it — so there's nowhere useful to catch it and say why.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


async def serve(port: int):
    """Start the service in-process; return the server and its task."""
    import uvicorn

    from assistant.server import create_app

    config = uvicorn.Config(
        create_app(),
        host="127.0.0.1",
        port=port,
        log_level=os.environ.get("LOG_LEVEL", "warning"),
    )
    server = uvicorn.Server(config)
    # Ours to handle: uvicorn's would swallow Ctrl-C before the client sees it.
    server.install_signal_handlers = lambda: None
    task = asyncio.create_task(server.serve())

    for _ in range(200):
        if server.started:
            return server, task
        if task.done():
            await task
        await asyncio.sleep(0.05)
    raise RuntimeError(f"the service did not come up on port {port}")


async def main_async(args) -> int:
    token = os.environ.get("ASSISTANT_TOKEN", "").strip()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Run: python run_setup.py")
        return 1
    if not token:
        print("ASSISTANT_TOKEN is not set. Run: python run_setup.py")
        return 1
    if not _port_is_free(args.port):
        raise RuntimeError(
            f"port {args.port} is already in use — run_server.py, perhaps. "
            f"Stop it, or use --port {args.port + 1}."
        )

    server, serving = await serve(args.port)
    url = f"http://127.0.0.1:{args.port}"
    face = f"{url}/avatar#token={token}"

    spoken = args.listen
    if not args.listen and not args.voice:
        from assistant.audio import Microphone

        spoken = Microphone.available()

    print(_c("2", f"\n  service on {url}"))
    print(_c("2", "  her face:  ") + _c("36", face))
    if args.open:
        webbrowser.open(face)

    try:
        if spoken:
            import run_listen

            await run_listen.run(url, token)
        else:
            import run_voice

            await run_voice.run(url, token)
    finally:
        # Let uvicorn finish its own shutdown before the loop closes under it,
        # or every exit ends in a cancelled-lifespan traceback.
        server.should_exit = True
        try:
            await asyncio.wait_for(serving, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--listen", action="store_true", help="talk to her out loud")
    mode.add_argument("--voice", action="store_true", help="type, hear her answer")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ASSISTANT_PORT", "8000")))
    parser.add_argument("--open", action="store_true", help="open her face in a browser")
    args = parser.parse_args()

    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print()
        return 0
    except RuntimeError as exc:
        print(_c("31", f"  {exc}"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
