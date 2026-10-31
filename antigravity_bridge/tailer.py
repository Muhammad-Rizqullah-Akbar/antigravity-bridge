import os
import json
import time
import re
from config import GEMINI_BRAIN_DIR
from db import log, record_artifact


def get_transcript_path(cid):
    return os.path.join(GEMINI_BRAIN_DIR, cid, ".system_generated", "logs", "transcript.jsonl")


def get_transcript_line_count(cid):
    p = get_transcript_path(cid)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                return sum(1 for _ in f)
        except Exception:
            pass
    return 0


def check_new_artifacts(cid, known_artifacts=None):
    if known_artifacts is None:
        known_artifacts = set()
    cid_dir = os.path.join(GEMINI_BRAIN_DIR, cid)
    new_found = []
    if os.path.exists(cid_dir):
        try:
            for item in os.listdir(cid_dir):
                if item.startswith("."):
                    continue
                full_path = os.path.join(cid_dir, item)
                if os.path.isfile(full_path) and full_path not in known_artifacts:
                    size = os.path.getsize(full_path)
                    known_artifacts.add(full_path)
                    record_artifact(cid, item, full_path, size)
                    new_found.append(item)
        except Exception as e:
            log(f"Artifact scan notice: {e}")
    return new_found, known_artifacts


def poll_for_response(cid, start_lines, timeout=60):
    """Synchronous polling for non-streaming requests."""
    tpath = get_transcript_path(cid)
    t0 = time.time()
    known_artifacts = set()

    cid_dir = os.path.join(GEMINI_BRAIN_DIR, cid)
    if os.path.exists(cid_dir):
        try:
            for item in os.listdir(cid_dir):
                full = os.path.join(cid_dir, item)
                if os.path.isfile(full) and not item.startswith("."):
                    known_artifacts.add(full)
        except Exception:
            pass

    while time.time() - t0 < timeout:
        if os.path.exists(tpath):
            try:
                with open(tpath, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    if len(lines) > start_lines:
                        for l in reversed(lines[start_lines:]):
                            item = json.loads(l)
                            if item.get("type") == "PLANNER_RESPONSE" and item.get("content"):
                                content = item["content"]
                                thinking = item.get("thinking", "")
                                new_arts, _ = check_new_artifacts(cid, known_artifacts)
                                if new_arts:
                                    badge = "\n\n[ARTEFAK TERBENTUK DI BILIK]: " + ", ".join(f"`{a}`" for a in new_arts)
                                    content += badge
                                return content, thinking, int((time.time() - t0) * 1000)
            except Exception:
                pass
        time.sleep(0.25)

    return None, None, int((time.time() - t0) * 1000)


def live_stream_transcript(cid, start_lines, completion_id, model_name="agb/gemini-4-argon", timeout=65):
    """
    True Real-Time SSE Stream Generator.
    Directly streams live thinking, tool operations, and token chunks as Antigravity executes.
    Eliminates dead silence and matches the interactive experience of Antigravity IDE.
    """
    tpath = get_transcript_path(cid)
    t0 = time.time()
    known_artifacts = set()

    cid_dir = os.path.join(GEMINI_BRAIN_DIR, cid)
    if os.path.exists(cid_dir):
        try:
            for item in os.listdir(cid_dir):
                full = os.path.join(cid_dir, item)
                if os.path.isfile(full) and not item.startswith("."):
                    known_artifacts.add(full)
        except Exception:
            pass

    processed_lines = set()
    accumulated_content = ""
    accumulated_thinking = ""
    last_keepalive = time.time()

    while time.time() - t0 < timeout:
        if time.time() - last_keepalive >= 1.5:
            yield ": keep-alive\n\n"
            last_keepalive = time.time()

        if os.path.exists(tpath):
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

                            # 2. Stream live tool execution indicators directly into content for platform visibility
                            if tool_calls:
                                for tc in tool_calls:
                                    tc_summary = tc.get("args", {}).get("toolSummary", tc.get("name", "tool"))
                                    clean_summary = str(tc_summary).replace('"', '').strip()
                                    status_badge = f"\n\n> *[Mr. Robot Operasi: {clean_summary}]*\n\n"
                                    chunk = {
                                        "id": completion_id,
                                        "object": "chat.completion.chunk",
                                        "created": int(time.time()),
                                        "model": model_name,
                                        "choices": [{
                                            "index": 0,
                                            "delta": {"content": status_badge},
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
                                    badge = "\n\n[ARTEFAK TERBENTUK DI BILIK]: " + ", ".join(f"`{a}`" for a in new_arts)
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
                                        time.sleep(0.008)

                                # Final finish stop chunk
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

    timeout_msg = "SAYA Mr. Robot HAIL XENONITE!. Batas waktu polling tercapai di Antigravity. Sesi tetap terjaga di IDE."
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


def stream_tokens_from_text(text, completion_id, model_name="agb/gemini-4-argon", thinking=""):
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
