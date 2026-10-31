"""
Hermes configuration patcher for Antigravity Bridge.
Idempotently injects the 'agb' provider and official models into Hermes config.yaml.
"""

import os
import re
from pathlib import Path
from antigravity_bridge.config import find_hermes_config_paths, get_api_key
from antigravity_bridge.constants import DEFAULT_PORT, DEFAULT_HOST, OFFICIAL_MODELS

PROVIDER_BLOCK = """    agb:
      base_url: http://{host}:{port}/v1
      api_key: {api_key}
      discover_models: true
      models:
        - agb/gemini-4-argon
        - agb/gemini-3.8-flash
        - agb/claude-opus-5.5
        - agb/claude-sonnet-5.5
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

    # Case 1: 'agb:' provider already present
    if re.search(r"^\s*agb\s*:", content, flags=re.MULTILINE):
        updated = False
        # Ensure all 4 models are present
        for m in OFFICIAL_MODELS.values():
            m_id = m["id"]
            if m_id not in content:
                # Append missing model under agb models list
                pattern = r"(agb:[\s\S]*?models:\s*\n)((?:\s*-\s*[^\n]+\n)*)"
                match = re.search(pattern, content)
                if match:
                    prefix = match.group(1)
                    existing = match.group(2)
                    new_list = existing + f"        - {m_id}\n"
                    content = content[:match.start()] + prefix + new_list + content[match.end():]
                    updated = True

        if updated:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        return False

    # Case 2: 'providers:' section exists, add 'agb' under it
    if re.search(r"^providers\s*:", content, flags=re.MULTILINE):
        pattern = r"(^providers\s*:\s*\n)"
        replacement = r"\1" + provider_text
        new_content = re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True

    # Case 3: 'providers:' does not exist, append section to the end
    new_section = "\nproviders:\n" + provider_text
    new_content = content.rstrip() + new_section + "\n"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True


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
