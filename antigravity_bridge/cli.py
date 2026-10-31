"""
Command Line Interface (CLI) for Antigravity Bridge.
Provides subcommands: init, start, stop, status, models.
"""

import argparse
import sys
import os
import json
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from antigravity_bridge.constants import (
    DEFAULT_PORT,
    DEFAULT_HOST,
    OFFICIAL_MODELS,
    SERVER_VERSION,
)
from antigravity_bridge.config import (
    find_agentapi_path,
    find_brain_dir,
    get_db_path,
)
from antigravity_bridge.db import init_db
from antigravity_bridge.patcher import auto_patch_all_hermes_configs
from antigravity_bridge.server import run_server


def check_antigravity_cli() -> bool:
    """Verify Antigravity CLI binary exists and is executable."""
    agentapi = find_agentapi_path()
    if not os.path.exists(agentapi):
        print(f"[!] Antigravity CLI not found at: {agentapi}")
        print("    Please install Antigravity CLI or set ANTIGRAVITY_AGENTAPI_PATH.")
        return False
    print(f"[+] Antigravity CLI located: {agentapi}")
    return True


def init_cmd(args=None):
    """Automated initialization: connects Hermes with Antigravity."""
    print("============================================================")
    print(" ANTIGRAVITY BRIDGE AUTOMATED SETUP (v" + SERVER_VERSION + ")")
    print("============================================================")

    # 1. Verify Antigravity CLI
    cli_ok = check_antigravity_cli()
    if not cli_ok:
        print("[!] Warning: Antigravity CLI was not found automatically.")
        print("    You can still continue if it is accessible via PATH.")

    # 2. Verify Brain directory
    brain_dir = find_brain_dir()
    if brain_dir.is_dir():
        print(f"[+] Antigravity Brain directory found: {brain_dir}")
    else:
        print(f"[*] Antigravity Brain directory will be created at: {brain_dir}")

    # 3. Initialize SQLite Ledger
    print("[*] Initializing state ledger...")
    init_db()
    print(f"[+] SQLite database ready at: {get_db_path()}")

    # 4. Patch Hermes Configuration
    print("[*] Searching for Hermes configuration files...")
    patched = auto_patch_all_hermes_configs()
    if patched:
        for p in patched:
            print(f"[+] Successfully patched: {p}")
    else:
        print("[*] Hermes configuration is already configured with provider 'agb'.")

    print("\n============================================================")
    print(" SETUP COMPLETE! ")
    print("============================================================")
    print("Hermes is now configured to route queries through Antigravity Bridge.")
    print("Supported models:")
    for m in OFFICIAL_MODELS.values():
        print(f"  - {m['id']} : {m['name']}")
    print("\nHow to start:")
    print("  Run in terminal: agb start")
    print("  Or run daemon:   agb start --daemon")
    print("\nIn your Telegram or chat client, select model via:")
    print("  /model agb/gemini-4-argon")
    print("  /model agb/gemini-3.8-flash")
    print("  /model agb/claude-opus-5.5")
    print("  /model agb/claude-sonnet-5.5")
    print("============================================================")


def start_cmd(args):
    """Start bridge server in foreground or background."""
    host = args.host if hasattr(args, "host") and args.host else DEFAULT_HOST
    port = args.port if hasattr(args, "port") and args.port else DEFAULT_PORT

    if hasattr(args, "daemon") and args.daemon:
        print(f"[*] Starting Antigravity Bridge daemon on http://{host}:{port}/...")
        cmd = [sys.executable, "-m", "antigravity_bridge.server_runner", "--host", host, "--port", str(port)]
        if sys.platform == "win32":
            subprocess.Popen(
                cmd,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                close_fds=True
            )
        else:
            subprocess.Popen(cmd, start_new_session=True, close_fds=True)
        print(f"[+] Daemon spawned in background on port {port}.")
        return

    run_server(host=host, port=port)


def stop_cmd(args):
    """Stop running bridge server."""
    port = args.port if hasattr(args, "port") and args.port else DEFAULT_PORT
    host = args.host if hasattr(args, "host") and args.host else DEFAULT_HOST
    url = f"http://{host}:{port}/shutdown"

    try:
        req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"[+] Antigravity Bridge stopped successfully: {resp.read().decode('utf-8')}")
    except Exception as e:
        print(f"[!] Could not send stop signal to {url}: {e}")
        print("    If process is hanging, terminate it via task manager or pkill.")


def status_cmd(args):
    """Query live bridge status."""
    port = args.port if hasattr(args, "port") and args.port else DEFAULT_PORT
    host = args.host if hasattr(args, "host") and args.host else DEFAULT_HOST
    url = f"http://{host}:{port}/healthz"

    try:
        with urllib.request.urlopen(url, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print("============================================================")
            print(" ANTIGRAVITY BRIDGE STATUS")
            print("============================================================")
            print(f"Status        : {data.get('status', 'unknown').upper()}")
            print(f"Version       : {data.get('version')}")
            print(f"Active Model  : {data.get('active_model')}")
            print(f"Active Session: {data.get('active_session')}")
            print(f"Uptime        : {data.get('uptime_seconds')} seconds")
            tel = data.get("telemetry", {})
            print(f"Requests      : {tel.get('total_requests', 0)}")
            print(f"Tokens        : {tel.get('total_tokens', 0)}")
            print("============================================================")
    except Exception as e:
        print(f"[!] Antigravity Bridge is OFFLINE or not responding on {url} ({e}).")


def models_cmd(args):
    """Display available official models."""
    print("============================================================")
    print(" OFFICIAL ANTIGRAVITY MODELS")
    print("============================================================")
    for m in OFFICIAL_MODELS.values():
        print(f"Identifier : {m['id']}")
        print(f"Name       : {m['name']}")
        print(f"Description: {m['desc']}")
        print(f"Tier       : {m['tier']}")
        print("------------------------------------------------------------")


def main():
    parser = argparse.ArgumentParser(
        prog="agb",
        description="Universal bridge connecting Hermes Agent with Google Antigravity models"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # init
    p_init = subparsers.add_parser("init", help="Automated setup: patch Hermes and initialize state")
    p_init.set_defaults(func=init_cmd)

    # start
    p_start = subparsers.add_parser("start", help="Start the bridge server")
    p_start.add_argument("--host", default=DEFAULT_HOST, help="Host to bind (default: 127.0.0.1)")
    p_start.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind (default: 8790)")
    p_start.add_argument("--daemon", action="store_true", help="Run server as a background daemon")
    p_start.set_defaults(func=start_cmd)

    # stop
    p_stop = subparsers.add_parser("stop", help="Stop running bridge server")
    p_stop.add_argument("--host", default=DEFAULT_HOST, help="Host of bridge server")
    p_stop.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port of bridge server")
    p_stop.set_defaults(func=stop_cmd)

    # status
    p_status = subparsers.add_parser("status", help="Check live bridge server status")
    p_status.add_argument("--host", default=DEFAULT_HOST, help="Host of bridge server")
    p_status.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port of bridge server")
    p_status.set_defaults(func=status_cmd)

    # models
    p_models = subparsers.add_parser("models", help="List official supported Antigravity models")
    p_models.set_defaults(func=models_cmd)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
