import os
import json
import time
import re
from config import GEMINI_BRAIN_DIR
from db import log, record_artifact


def clean_text_safety(text: str) -> str:
    """Enforces Xenonite safety principles: ZERO em-dash and ZERO 'doktrin'."""
    if not text:
        return ""
    cleaned = text.replace("\u2014", " - ").replace(" -- ", " - ")
    cleaned = re.sub(r"\bdoktrin\b", "prinsip", cleaned, flags=re.IGNORECASE)
    return cleaned


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


def format_tool_call(tc):
    """Formats tool calls with rich detail like an expert engineer working."""
    name = tc.get("name", "tool")
    args = tc.get("args", {})
    summary = clean_text_safety(str(args.get("toolSummary", "")).replace('"', '').strip())
    lines = []

    if name == "run_command":
        cmd = clean_text_safety(str(args.get("CommandLine", "")).replace('"', '').strip())
        label = f"Eksekusi Shell: {summary}" if summary else "Eksekusi Shell"
        lines.append(f"> 🛠️ **[{label}]**")
        if cmd:
            display_cmd = cmd[:120] + ("..." if len(cmd) > 120 else "")
            lines.append(f"> `$ {display_cmd}`")
    elif name in ("read_file", "edit_file", "write_file"):
        path = clean_text_safety(str(args.get("Path", "")).replace('"', '').strip())
        fname = os.path.basename(path) or path
        action_map = {
            "read_file": "Membaca Berkas",
            "edit_file": "Memodifikasi Berkas",
            "write_file": "Membuat Berkas"
        }
        lines.append(f"> 📂 **[{action_map.get(name, name)}]**: `{fname}`")
        if path:
            lines.append(f"> `Path: {path}`")
    elif name == "search_web":
        query = clean_text_safety(str(args.get("query", "")).replace('"', '').strip())
        lines.append(f"> 🌐 **[Riset Web]**: `{query}`")
    elif name == "call_mcp_tool":
        server = clean_text_safety(str(args.get("ServerName", "")).strip())
        tool = clean_text_safety(str(args.get("ToolName", "")).strip())
        lines.append(f"> 🔌 **[MCP Tool: {server} / {tool}]**")
    elif name in ("manage_task", "invoke_subagent", "define_subagent"):
        lines.append(f"> 🤖 **[Orkestrasi Agen / Task: {name}]**")
    else:
        label = f"{name}: {summary}" if summary else name
        lines.append(f"> ⚙️ **[Operasi: {label}]**")

    return "\n".join(lines) + "\n"


def format_tool_result(content):
    """Formats tool outputs and observations for real-time progress tracking."""
    if not content or not str(content).strip():
        return ""
    c = clean_text_safety(str(content).strip())

    if "Command exited with code 0" in c:
        out_idx = c.find("Command output:")
        if out_idx != -1:
            raw_out = c[out_idx + len("Command output:"):].strip()
            first_lines = [l.strip() for l in raw_out.splitlines() if l.strip()][:2]
            snippet = " | ".join(first_lines)[:120] if first_lines else "Sukses tanpa output."
            return f"> ↳ ✅ **Hasil (Exit 0)**: `{snippet}`\n\n"
        return "> ↳ ✅ **Hasil (Exit 0)**: Operasi sukses dieksekusi.\n\n"
    elif "Command exited with code" in c:
        m = re.search(r"Command exited with code (\d+)", c)
        code = m.group(1) if m else "1"
        return f"> ↳ ⚠️ **Hasil (Exit {code})**: Terdapat kendala eksekusi.\n\n"
    elif "Showing lines" in c:
        m = re.search(r"Showing lines (\d+)-(\d+) of (\d+)", c)
        if m:
            return f"> ↳ 📄 **Observasi**: Membaca baris {m.group(1)}-{m.group(2)} dari {m.group(3)} baris data.\n\n"
        return "> ↳ 📄 **Observasi**: Isi berkas berhasil dibaca.\n\n"
    elif "Created file" in c:
        return "> ↳ 💾 **Observasi**: Berkas berhasil dibuat dan disimpan.\n\n"
    elif "Tool execution was canceled" in c:
        return "> ↳ ⏹️ **Observasi**: Eksekusi dibatalkan.\n\n"
    else:
        first_line = c.splitlines()[0][:100]
        return f"> ↳ 📋 **Observasi**: `{first_line}`\n\n"


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
                                content = clean_text_safety(item["content"])
                                thinking = clean_text_safety(item.get("thinking", ""))
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
    Eliminates dead silence and matches the interactive experience of an expert remote engineer.
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
    thinking_started = False

    # 1. Announce assistant role immediately so client recognizes streaming start
    role_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant", "content": ""},
            "finish_reason": None
        }]
    }
    yield f"data: {json.dumps(role_chunk, ensure_ascii=False)}\n\n"

    # 2. Emit an immediate live status token so Telegram creates the message bubble on second 0
    init_badge = "⚡ **[Mr. Robot Nucleus | Antigravity Engine Aktif...]**\n\n"
    init_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{
            "index": 0,
            "delta": {"content": init_badge},
            "finish_reason": None
        }]
    }
    yield f"data: {json.dumps(init_chunk, ensure_ascii=False)}\n\n"

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
                            thinking = clean_text_safety(item.get("thinking", ""))
                            tool_calls = item.get("tool_calls", [])
                            content = clean_text_safety(item.get("content", ""))

                            # 1. Stream live reasoning visibly into content without <think> tags (so Hermes does not scrub it)
                            if thinking and thinking != accumulated_thinking:
                                if thinking.startswith(accumulated_thinking):
                                    new_part = thinking[len(accumulated_thinking):]
                                else:
                                    new_part = thinking
                                accumulated_thinking = thinking

                                if not thinking_started:
                                    thinking_started = True
                                    think_header = "> 💭 **[Analisis Operasional]**:\n> "
                                    chunk = {
                                        "id": completion_id,
                                        "object": "chat.completion.chunk",
                                        "created": int(time.time()),
                                        "model": model_name,
                                        "choices": [{
                                            "index": 0,
                                            "delta": {"content": think_header, "reasoning_content": ""},
                                            "finish_reason": None
                                        }]
                                    }
                                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

                                for piece in re.split(r"(\s+)", new_part):
                                    if piece:
                                        piece_formatted = piece.replace("\n", "\n> ")
                                        chunk = {
                                            "id": completion_id,
                                            "object": "chat.completion.chunk",
                                            "created": int(time.time()),
                                            "model": model_name,
                                            "choices": [{
                                                "index": 0,
                                                "delta": {"content": piece_formatted, "reasoning_content": piece},
                                                "finish_reason": None
                                            }]
                                        }
                                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                                        time.sleep(0.003)

                            # 2. Stream tool calls with exact arguments and context
                            if tool_calls:
                                if thinking_started:
                                    thinking_started = False
                                    close_chunk = {
                                        "id": completion_id,
                                        "object": "chat.completion.chunk",
                                        "created": int(time.time()),
                                        "model": model_name,
                                        "choices": [{
                                            "index": 0,
                                            "delta": {"content": "\n\n"},
                                            "finish_reason": None
                                        }]
                                    }
                                    yield f"data: {json.dumps(close_chunk, ensure_ascii=False)}\n\n"

                                for tc in tool_calls:
                                    tc_text = format_tool_call(tc)
                                    chunk = {
                                        "id": completion_id,
                                        "object": "chat.completion.chunk",
                                        "created": int(time.time()),
                                        "model": model_name,
                                        "choices": [{
                                            "index": 0,
                                            "delta": {"content": f"\n{tc_text}"},
                                            "finish_reason": None
                                        }]
                                    }
                                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

                            # 3. Stream final content words when ready
                            if content:
                                if thinking_started:
                                    thinking_started = False
                                    close_chunk = {
                                        "id": completion_id,
                                        "object": "chat.completion.chunk",
                                        "created": int(time.time()),
                                        "model": model_name,
                                        "choices": [{
                                            "index": 0,
                                            "delta": {"content": "\n\n"},
                                            "finish_reason": None
                                        }]
                                    }
                                    yield f"data: {json.dumps(close_chunk, ensure_ascii=False)}\n\n"

                                divider = "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                                div_chunk = {
                                    "id": completion_id,
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": model_name,
                                    "choices": [{
                                        "index": 0,
                                        "delta": {"content": divider},
                                        "finish_reason": None
                                    }]
                                }
                                yield f"data: {json.dumps(div_chunk, ensure_ascii=False)}\n\n"

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
                                        time.sleep(0.006)

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

                        elif item_type == "GENERIC":
                            # Stream tool execution results and observations
                            g_content = item.get("content", "")
                            res_text = format_tool_result(g_content)
                            if res_text:
                                chunk = {
                                    "id": completion_id,
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": model_name,
                                    "choices": [{
                                        "index": 0,
                                        "delta": {"content": res_text},
                                        "finish_reason": None
                                    }]
                                }
                                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

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
    safe_text = clean_text_safety(text)
    if thinking and thinking.strip():
        safe_thinking = clean_text_safety(thinking)
        header = "> 💭 **[Analisis Operasional]**:\n> "
        h_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{
                "index": 0,
                "delta": {"content": header},
                "finish_reason": None
            }]
        }
        yield f"data: {json.dumps(h_chunk, ensure_ascii=False)}\n\n"

        for piece in re.split(r"(\s+)", safe_thinking):
            if piece:
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model_name,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": piece.replace("\n", "\n> "), "reasoning_content": piece},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': model_name, 'choices': [{'index': 0, 'delta': {'content': '\n\n'}, 'finish_reason': None}]}, ensure_ascii=False)}\n\n"

    for piece in re.split(r"(\s+)", safe_text):
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
