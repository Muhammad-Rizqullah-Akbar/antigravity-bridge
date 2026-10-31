"""
Configuration and cross-platform path resolution for Antigravity Bridge.
"""

import os
import sys
import shutil
from pathlib import Path
from antigravity_bridge.constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_API_KEY,
)


def get_bridge_home() -> Path:
    """Return the base directory for bridge data and configuration (~/.antigravity-bridge)."""
    custom = os.environ.get("ANTIGRAVITY_BRIDGE_HOME")
    if custom:
        p = Path(custom).expanduser().resolve()
    else:
        p = Path.home() / ".antigravity-bridge"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_data_dir() -> Path:
    """Return data directory."""
    d = get_bridge_home() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_logs_dir() -> Path:
    """Return logs directory."""
    d = get_bridge_home() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_db_path() -> Path:
    """Return SQLite database path."""
    return get_data_dir() / "bridge.db"


def find_language_server_path() -> str:
    """Locate language_server native binary on Windows/Linux/macOS if present."""
    home = Path.home()
    candidates = [
        home / "AppData" / "Local" / "Programs" / "antigravity" / "resources" / "bin" / "language_server.exe",
        Path("C:/Program Files/antigravity/resources/bin/language_server.exe"),
        home / ".local" / "share" / "antigravity" / "bin" / "language_server",
        Path("/usr/local/share/antigravity/bin/language_server"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return ""


def find_agentapi_path() -> str:
    """
    Locate Antigravity agentapi binary across Windows, Linux, and macOS.
    """
    custom = os.environ.get("ANTIGRAVITY_AGENTAPI_PATH")
    if custom and os.path.exists(custom):
        return custom

    home = Path.home()
    candidates = [
        home / ".gemini" / "antigravity" / "bin" / "agentapi.bat",
        home / ".gemini" / "antigravity" / "bin" / "agentapi.cmd",
        home / ".gemini" / "antigravity" / "bin" / "agentapi.exe",
        home / ".gemini" / "antigravity" / "bin" / "agy.bat",
        home / ".gemini" / "antigravity" / "bin" / "agy.exe",
        home / ".gemini" / "antigravity" / "bin" / "agentapi",
        home / ".gemini" / "antigravity" / "bin" / "agy",
        home / ".local" / "bin" / "agentapi",
        home / ".local" / "bin" / "agy",
        Path("/usr/local/bin/agentapi"),
        Path("/usr/local/bin/agy"),
    ]

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    found = shutil.which("agentapi") or shutil.which("agy")
    if found:
        return found

    if sys.platform == "win32":
        return str(home / ".gemini" / "antigravity" / "bin" / "agentapi.bat")
    return str(home / ".gemini" / "antigravity" / "bin" / "agentapi")


def get_agentapi_cmd() -> tuple:
    """
    Return (cmd_list, use_shell).
    Prefers direct language_server binary on Windows to avoid cmd.exe multiline argument truncation.
    """
    native = find_language_server_path()
    if native and os.path.exists(native):
        return [native, "agentapi"], False
    agentapi = find_agentapi_path()
    use_shell = True if sys.platform == "win32" and agentapi.endswith((".bat", ".cmd")) else False
    return [agentapi], use_shell


def find_brain_dir() -> Path:
    """Locate Antigravity brain storage directory containing conversation transcripts."""
    custom = os.environ.get("ANTIGRAVITY_BRAIN_DIR")
    if custom and os.path.isdir(custom):
        return Path(custom)

    home = Path.home()
    candidates = [
        home / ".gemini" / "antigravity" / "brain",
        home / ".antigravity" / "brain",
    ]
    for c in candidates:
        if c.is_dir():
            return c

    return home / ".gemini" / "antigravity" / "brain"


def find_hermes_config_paths() -> list:
    """Find all Hermes config.yaml locations across global and profile paths."""
    home = Path.home()
    found = []

    candidates = [
        home / ".hermes" / "config.yaml",
    ]

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            win_hermes = Path(local_app_data) / "hermes"
            candidates.append(win_hermes / "config.yaml")
            profiles_dir = win_hermes / "profiles"
            if profiles_dir.is_dir():
                for profile in profiles_dir.iterdir():
                    if profile.is_dir():
                        p_conf = profile / "config.yaml"
                        if p_conf.is_file():
                            candidates.append(p_conf)

    unix_profiles = home / ".hermes" / "profiles"
    if unix_profiles.is_dir():
        for profile in unix_profiles.iterdir():
            if profile.is_dir():
                p_conf = profile / "config.yaml"
                if p_conf.is_file():
                    candidates.append(p_conf)

    for c in candidates:
        if c.is_file() and c not in found:
            found.append(c)

    return found


def get_api_key() -> str:
    """Retrieve bridge API key from environment or fallback to default."""
    return os.environ.get("ANTIGRAVITY_BRIDGE_API_KEY", DEFAULT_API_KEY)


def get_server_host() -> str:
    """Retrieve host to bind."""
    return os.environ.get("ANTIGRAVITY_BRIDGE_HOST", DEFAULT_HOST)


def get_server_port() -> int:
    """Retrieve port to bind."""
    val = os.environ.get("ANTIGRAVITY_BRIDGE_PORT")
    if val:
        try:
            return int(val)
        except ValueError:
            pass
    return DEFAULT_PORT
