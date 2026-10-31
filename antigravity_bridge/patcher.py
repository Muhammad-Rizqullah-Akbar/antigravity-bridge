"""
Hermes configuration patcher for Antigravity Bridge.
Idempotently injects the 'agb' provider and official models into Hermes config.yaml.
"""

import os
import re
from pathlib import Path
from antigravity_bridge.config import find_hermes_config_paths, get_api_key
from antigravity_bridge.constants import DEFAULT_PORT, DEFAULT_HOST, OFFICIAL_MODELS

PROVIDER_BLOCK = """  agb:
    name: agb
    base_url: http://{host}:{port}/v1
    api_key: {api_key}
    discover_models: true
    models:
      agb/gemini-4-argon:
        context_length: 1048576
      agb/gemini-3.8-flash:
        context_length: 1048576
      agb/claude-opus-5.5:
        context_length: 1048576
      agb/claude-sonnet-5.5:
        context_length: 1048576
"""


def patch_hermes_config(file_path: Path, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    """
    Patch a single Hermes config.yaml file to include the 'agb' provider.
    Returns True if file was updated, False if already up to date.
    """
    if not file_path.is_file():
        return False

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    api_key = get_api_key()
    provider_text = PROVIDER_BLOCK.format(host=host, port=port, api_key=api_key)

    # Clean any malformed agb block first
    cleaned = re.sub(r'    agb:[\s\S]*?(?=\n  [a-zA-Z0-9_-]+:|\n[a-zA-Z0-9_-]+:|$)', '', content)
    cleaned = re.sub(r'  agb:[\s\S]*?(?=\n  [a-zA-Z0-9_-]+:|\n[a-zA-Z0-9_-]+:|$)', '', cleaned)

    if "providers:" in cleaned:
        new_content = re.sub(r'(providers:\s*\n)', r'\1' + provider_text, cleaned, count=1)
    else:
        new_content = cleaned.rstrip() + "\nproviders:\n" + provider_text

    if new_content != content:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True

    return False


def auto_patch_all_hermes_configs(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> list:
    """
    Locate and patch all available Hermes configuration files.
    Returns list of paths that were modified.
    """
    configs = find_hermes_config_paths()
    patched = []
    for cfg in configs:
        if patch_hermes_config(cfg, host=host, port=port):
            patched.append(cfg)
    return patched
