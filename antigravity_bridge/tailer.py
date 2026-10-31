"""
Transcript tailing and reasoning extraction for Antigravity Bridge.
"""

import os
import json
import time
from pathlib import Path
from antigravity_bridge.config import find_brain_dir
from antigravity_bridge.db import log, record_artifact


def get_transcript_path(cid: str) -> Path:
    """Return path to the conversation transcript file."""
    brain = find_brain_dir()
    return brain / cid / ".system_generated" / "logs" / "transcript.jsonl"


def get_transcript_line_count(cid: str) -> int:
    """Return line count of current transcript."""
    tpath = get_transcript_path(cid)
    if tpath.is_file():
        try:
            with open(tpath, "r", encoding="utf-8", errors="ignore") as f:
                return sum(1 for _ in f)
        except Exception:
            pass
    return 0


def check_new_artifacts(cid: str, known_artifacts: set = None):
    """Scan conversation folder for new artifacts created by the agent."""
    if known_artifacts is None:
        known_artifacts = set()
    brain = find_brain_dir()
    cid_dir = brain / cid
    new_found = []

    if cid_dir.is_dir():
        try:
            for item in cid_dir.iterdir():
                if item.name.startswith("."):
                    continue
                if item.is_file():
                    p_str = str(item)
                    if p_str not in known_artifacts:
                        size = item.stat().st_size
                        known_artifacts.add(p_str)
                        record_artifact(cid, item.name, p_str, size)
                        new_found.append(item.name)
        except Exception as e:
            log(f"Artifact scan notice: {e}")

    return new_found, known_artifacts


def poll_for_response(cid: str, start_lines: int, timeout: int = 60):
    """
    Poll transcript for PLANNER_RESPONSE.
    Returns: (reply_text, thinking_text, latency_ms)
    """
    tpath = get_transcript_path(cid)
    t0 = time.time()
    known_artifacts = set()

    # Pre-populate existing artifacts
    brain = find_brain_dir()
    cid_dir = brain / cid
    if cid_dir.is_dir():
        try:
            for item in cid_dir.iterdir():
                if item.is_file() and not item.name.startswith("."):
                    known_artifacts.add(str(item))
        except Exception:
            pass

    last_size = 0
    while time.time() - t0 < timeout:
        if tpath.is_file():
            try:
                curr_size = tpath.stat().st_size
                if curr_size != last_size:
                    last_size = curr_size
                    with open(tpath, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        if len(lines) > start_lines:
                            for line in reversed(lines[start_lines:]):
                                try:
                                    item = json.loads(line)
                                except Exception:
                                    continue

                                if item.get("type") == "PLANNER_RESPONSE" and item.get("content"):
                                    content = item["content"]
                                    thinking = item.get("thinking", "")

                                    # Check for artifacts
                                    new_arts, _ = check_new_artifacts(cid, known_artifacts)
                                    if new_arts:
                                        badge = "\n\n[Artifacts generated]: " + ", ".join(f"`{a}`" for a in new_arts)
                                        content += badge

                                    latency_ms = int((time.time() - t0) * 1000)
                                    return content, thinking, latency_ms
            except Exception as e:
                log(f"Polling warning: {e}")

        time.sleep(0.35)

    latency_ms = int((time.time() - t0) * 1000)
    return "", "", latency_ms
