"""
Background runner entrypoint for daemon mode.
"""

import argparse
from antigravity_bridge.server import run_server
from antigravity_bridge.constants import DEFAULT_PORT, DEFAULT_HOST


def main():
    parser = argparse.ArgumentParser(description="Daemon runner")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
