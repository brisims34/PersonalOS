"""Start PersonalOS.

    python run.py                 http://127.0.0.1:5000
    python run.py --debug         auto-reload, full tracebacks
    python run.py --no-browser    do not open a browser window
    python run.py --port 5050

The host is fixed at 127.0.0.1 and is not configurable. This application holds
client engagement data on a single machine and has no authentication because
it never listens on a network interface (CLAUDE.md rule 1).
"""
import argparse
import os
import sys
import threading
import webbrowser

from app import configure_logging, create_app

HOST = "127.0.0.1"
DEFAULT_PORT = 5000


def _open_browser(url, delay=1.2):
    threading.Timer(delay, lambda: webbrowser.open_new_tab(url)).start()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run PersonalOS locally.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--debug", action="store_true", help="auto-reload and full tracebacks")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    configure_logging()

    try:
        app = create_app()
    except Exception as exc:  # migration failure, unreadable data directory
        print(f"\nPersonalOS could not start:\n  {exc}\n", file=sys.stderr)
        return 1

    url = f"http://{HOST}:{args.port}/"
    # Under the reloader the parent process re-executes this file; without the
    # guard the browser opens twice on every restart.
    is_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if not args.no_browser and not is_reloader_child:
        _open_browser(url)

    print(f"\n  PersonalOS  →  {url}\n  Ctrl-C to stop.\n")
    app.run(host=HOST, port=args.port, debug=args.debug, use_reloader=args.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
