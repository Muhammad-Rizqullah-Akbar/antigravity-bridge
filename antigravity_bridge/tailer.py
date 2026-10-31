"""
Transcript tailing and real-time streaming extraction for Antigravity Bridge.
"""

import os
import json
import time
import re
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
    """Synchronous polling for non-streaming requests."""
    tpath = get_transcript_path(cid)
    t0 = time.time()
    known_artifacts = set()

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

                                    new_arts, _ = check_new_artifacts(cid, known_artifacts)
                                    if new_arts:
                                        badge = "\n\n[Artifacts generated]: " + ", ".join(f"`{a}`" for a in new_arts)
                                        content += badge

                                    latency_ms = int((time.time() - t0) * 1000)
                                    return content, thinking, latency_ms
            except Exception as e:
                log(f"Polling warning: {e}")

        time.sleep(0.25)

    latency_ms = int((time.time() - t0) * 1000)
    return "", "", latency_ms


def live_stream_transcript(cid: str, start_lines: int, completion_id: str, model_name: str, timeout: int = 65):
    """
    True Real-Time SSE Stream Generator.
    Directly streams live thinking, tool operations, and token chunks as Antigravity executes.
    Matches the interactive streaming experience of Antigravity IDE.
    """
    tpath = get_transcript_path(cid)
    t0 = time.time()
    known_artifacts = set()

    brain = find_brain_dir()
    cid_dir = brain / cid
    if cid_dir.is_dir():
        try:
            for item in cid_dir.iterdir():
                if item.is_file() and not item.name.startswith("."):
                    known_artifacts.add(str(item))
        except Exception:
            pass

    processed_lines = set()
    accumulated_content = ""
    accumulated_thinking = ""

    while time.time() - t0 < timeout:
        if tpath.is_file():
            try:
                with open(tpath, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()

                if len(lines) > start_lines:
                    for line_idx in range(start_lines, len(lines)):
                        if line_idx in processed_lines:
                            continue

                        line_str = lines[line_idx].strip()
                        if not line_str:
                            processed_lines.add(line_idx)
                            continue

                        try:
                            item = json.loads(line_str)
                        except Exception:
                            continue

                        item_type = item.get("type")

                        if item_type == "PLANNER_RESPONSE":
                            thinking = item.get("thinking", "")
                            tool_calls = item.get("tool_calls", [])
                            content = item.get("content", "")

                            # 1. Stream live reasoning deltas as soon as generated
                            if thinking and thinking != accumulated_thinking:
                                if thinking.startswith(accumulated_thinking):
                                    new_part = thinking[len(accumulated_thinking):]
                                else:
                                    new_part = thinking
                                accumulated_thinking = thinking

                                for piece in re.split(r"(\s+)", new_part):
                                    if piece:
                                        chunk = {
                                            "id": completion_id,
                                            "object": "chat.completion.chunk",
                                            "created": int(time.time()),
                                            "model": model_name,
                                            "choices": [{
                                                "index": 0,
                                                "delta": {"reasoning_content": piece},
                                                "finish_reason": None
                                            }]
                                        }
                                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                                        time.sleep(0.004)

                            # 2. Stream live tool execution indicators
                            if tool_calls:
                                for tc in tool_calls:
                                    tc_summary = tc.get("args", {}).get("toolSummary", tc.get("name", "tool"))
                                    clean_summary = str(tc_summary).replace('"', '').strip()
                                    status_badge = f"\n\n> *[Tool Execution: {clean_summary}]*\n\n"
                                    chunk = {
                                        "id": completion_id,
                                        "object": "chat.completion.chunk",
                                        "created": int(time.time()),
                                        "model": model_name,
                                        "choices": [{
                                            "index": 0,
                                            "delta": {"reasoning_content": status_badge},
                                            "finish_reason": None
                                        }]
                                    }
                                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

                            # 3. Stream final content words when ready
                            if content:
                                accumulated_content = content
                                processed_lines.add(line_idx)

                                new_arts, _ = check_new_artifacts(cid, known_artifacts)
                                if new_arts:
                                    badge = "\n\n[Artifacts generated]: " + ", ".join(f"`{a}`" for a in new_arts)
                                    content += badge
                                    accumulated_content = content

                                for piece in re.split(r"(\s+)", content):
                                    if piece:
                                        chunk = {
                                            "id": completion_id,
                                            "object": "chat.completion.chunk",
                                            "created": int(time.time()),
                                            "model": model_name,
                                            "choices": [{
                                                "index": 0,
                                                "delta": {"content": piece},
                                                "finish_reason": None
                                            }]
                                        }
                                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                                        time.sleep(0.007)

                                # Final stop chunk
                                stop_chunk = {
                                    "id": completion_id,
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": model_name,
                                    "choices": [{
                                        "index": 0,
                                        "delta": {},
                                        "finish_reason": "stop"
                                    }]
                                }
                                yield f"data: {json.dumps(stop_chunk)}\n\n"
                                yield "data: [DONE]\n\n"
                                return accumulated_content, accumulated_thinking, int((time.time() - t0) * 1000)

                        processed_lines.add(line_idx)
            except Exception as e:
                log(f"Live stream parser notice: {e}")

        time.sleep(0.2)

    timeout_msg = "Polling timeout reached on Antigravity Engine. Session remains intact in IDE."
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{
            "index": 0,
            "delta": {"content": timeout_msg},
            "finish_reason": "stop"
        }]
    }
    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"
    return timeout_msg, accumulated_thinking, int((time.time() - t0) * 1000)


def stream_tokens_from_text(text: str, completion_id: str, model_name: str, thinking: str = ""):
    """Fast generator for streaming command responses or static text."""
    if thinking and thinking.strip():
        for piece in re.split(r"(\s+)", thinking):
            if piece:
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model_name,
                    "choices": [{
                        "index": 0,
                        "delta": {"reasoning_content": piece},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    for piece in re.split(r"(\s+)", text):
        if piece:
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "delta": {"content": piece},
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            time.sleep(0.008)

    done_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop"
        }]
    }
    yield f"data: {json.dumps(done_chunk)}\n\n"
    yield "data: [DONE]\n\n"
