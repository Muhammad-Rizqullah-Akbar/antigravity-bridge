"""
Dispatch engine and conversation orchestrator for Antigravity Bridge.
Handles command interception, model tier selection, deduplication, and zero-splitting session flow.
"""

import os
import json
import time
import subprocess
import re
import threading
import hashlib
from antigravity_bridge.constants import (
    OFFICIAL_MODELS,
    DEFAULT_MODEL_KEY,
    MODEL_LOOKUP,
    SERVER_NAME,
    SERVER_VERSION,
)
from antigravity_bridge.config import find_brain_dir, get_agentapi_cmd
from antigravity_bridge.db import (
    log,
    get_config,
    set_config,
    get_active_cid,
    set_active_cid,
    record_history,
    increment_metric,
    get_telemetry_stats,
)
from antigravity_bridge.tailer import get_transcript_line_count, poll_for_response

START_TIME = time.time()
SESSION_LOCK = threading.Lock()
RECENT_DISPATCHES = {}


def resolve_model(model_name: str) -> dict:
    """Resolve an incoming model identifier to an official model definition."""
    if not model_name:
        saved = get_config("default_model", DEFAULT_MODEL_KEY)
        return OFFICIAL_MODELS.get(saved, OFFICIAL_MODELS[DEFAULT_MODEL_KEY])

    clean = model_name.strip().lower()
    if clean in MODEL_LOOKUP:
        key = MODEL_LOOKUP[clean]
        return OFFICIAL_MODELS[key]

    for key, info in OFFICIAL_MODELS.items():
        if key in clean or info["tier"] in clean:
            return info

    saved = get_config("default_model", DEFAULT_MODEL_KEY)
    return OFFICIAL_MODELS.get(saved, OFFICIAL_MODELS[DEFAULT_MODEL_KEY])


def extract_clean_prompt(messages: list) -> tuple:
    """
    Extract pure user prompt and system guidance from messages payload.
    Strips internal Hermes synthetic preambles so user questions are pristine.
    """
    raw_user_content = ""
    system_text = ""

    for msg in messages:
        role = msg.get("role")
        c = msg.get("content", "")
        if isinstance(c, list):
            parts = [p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text"]
            text_val = " ".join(parts)
        else:
            text_val = str(c)

        if role == "user":
            raw_user_content = text_val.strip()
        elif role == "system":
            system_text = text_val.strip()

    clean_user = re.sub(r"\[Note:\s*model was just switched[^\]]*\]\s*", "", raw_user_content).strip()
    if not clean_user:
        clean_user = raw_user_content.strip() or "Hello Antigravity"

    return clean_user, system_text


def list_brain_sessions(limit: int = 5) -> list:
    """Retrieve recent Antigravity brain sessions."""
    brain = find_brain_dir()
    sessions = []
    if not brain.is_dir():
        return sessions

    try:
        dirs = []
        for entry in brain.iterdir():
            if entry.is_dir() and len(entry.name) >= 30 and not entry.name.startswith("."):
                dirs.append((entry.name, entry.stat().st_mtime))

        dirs.sort(key=lambda x: x[1], reverse=True)
        for cid, mtime in dirs[:limit]:
            readable = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
            preview = ""
            tr_file = brain / cid / ".system_generated" / "logs" / "transcript.jsonl"
            if tr_file.is_file():
                try:
                    with open(tr_file, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            obj = json.loads(line)
                            if obj.get("type") == "USER_INPUT":
                                raw = obj.get("content", "")
                                clean_txt = re.sub(r"<[^>]+>", "", raw).strip()
                                preview = clean_txt[:35]
                                break
                except Exception:
                    pass
            sessions.append({
                "cid": cid,
                "time": readable,
                "preview": preview or "Session"
            })
    except Exception as e:
        log(f"Brain session listing error: {e}")

    return sessions


def handle_internal_command(cmd_text: str) -> str:
    """Handle slash commands for model switching and session management."""
    cmd = cmd_text.strip()
    lower = cmd.lower()

    if lower in ("/help", "help", "/panduan"):
        models_display = "\n".join(
            f"  - `/model {m['id']}` : {m['name']} ({m['desc']})"
            for m in OFFICIAL_MODELS.values()
        )
        return (
            "ANTIGRAVITY BRIDGE COMMANDS:\n\n"
            "Model Selection (Syntax: /model agb/<model-versi>):\n"
            f"{models_display}\n\n"
            "Session Management:\n"
            "  - `/status` : View connection telemetry, active model, and session ID.\n"
            "  - `/list`   : View recent conversation sessions in Antigravity Brain.\n"
            "  - `/attach <cid>` : Attach Hermes to an existing session from IDE.\n"
            "  - `/detach` : Disconnect session (next message starts a fresh one).\n"
            "  - `/new [title]` : Immediately initialize a new session.\n\n"
            "All other messages are routed directly to Antigravity AI Engine."
        )

    if lower in ("/status", "status", "/info"):
        cid = get_active_cid() or "No active session (will initialize on first message)"
        cur_model = get_config("default_model", DEFAULT_MODEL_KEY)
        m_info = OFFICIAL_MODELS.get(cur_model, OFFICIAL_MODELS[DEFAULT_MODEL_KEY])
        uptime_sec = int(time.time() - START_TIME)
        hrs = uptime_sec // 3600
        mins = (uptime_sec % 3600) // 60
        secs = uptime_sec % 60
        stats = get_telemetry_stats()

        return (
            f"ANTIGRAVITY BRIDGE STATUS:\n\n"
            f"- Status: ONLINE (Version {SERVER_VERSION})\n"
            f"- Active Model: {m_info['name']} (`{m_info['id']}`)\n"
            f"- Active Session: `{cid}`\n"
            f"- Uptime: {hrs}h {mins}m {secs}s\n"
            f"- Total Interactions: {stats['total_requests']}\n"
            f"- Estimated Tokens: {stats['total_tokens']}\n"
            f"- Session Integrity: Persistent continuous conversation history."
        )

    if lower in ("/list", "/sessions", "sessions"):
        sess_list = list_brain_sessions(6)
        if not sess_list:
            return "No previous conversation sessions found in Antigravity Brain."
        active_cid = get_active_cid()
        out = ["ANTIGRAVITY BRAIN SESSIONS:\n"]
        for idx, s in enumerate(sess_list, 1):
            mark = " [ACTIVE]" if s["cid"] == active_cid else ""
            out.append(f"{idx}. `{s['cid']}`{mark}\n   Time: {s['time']} | Topic: {s['preview']}")
        out.append("\nTo attach to a session, send: `/attach <SESSION_ID>`")
        return "\n".join(out)

    if lower.startswith("/attach "):
        target_cid = cmd.split(" ", 1)[1].strip()
        brain = find_brain_dir()
        target_path = brain / target_cid
        if target_path.is_dir():
            set_active_cid(target_cid, f"Attached session {time.strftime('%m-%d %H:%M')}")
            return (
                f"SESSION ATTACHED SUCCESSFULLY!\n\n"
                f"Session ID: `{target_cid}`\n"
                f"Hermes is now connected to this Antigravity session. Full context is preserved."
            )
        else:
            return f"Session ID `{target_cid}` was not found in Antigravity Brain."

    if lower in ("/detach", "/lepas"):
        set_config("active_cid", "")
        return "Session unlinked. Your next prompt will start a fresh, independent Antigravity session."

    if lower.startswith("/model"):
        parts = cmd.split(" ", 1)
        if len(parts) > 1 and parts[1].strip():
            raw_target = parts[1].strip()
            resolved = resolve_model(raw_target)
            set_config("default_model", resolved["alt_id"])
            return (
                f"MODEL SWITCHED SUCCESSFULLY!\n\n"
                f"- Active Model: **{resolved['name']}** (`{resolved['id']}`)\n"
                f"- Internal Tier: `{resolved['tier']}`\n"
                f"- Continuous History: Conversation session history is preserved without splitting.\n\n"
                f"Subsequent queries will be routed to {resolved['name']}."
            )
        else:
            cur = get_config("default_model", DEFAULT_MODEL_KEY)
            m_info = OFFICIAL_MODELS.get(cur, OFFICIAL_MODELS[DEFAULT_MODEL_KEY])
            options = "\n".join(f"  - `/model {m['id']}`" for m in OFFICIAL_MODELS.values())
            return (
                f"Current Model: **{m_info['name']}** (`{m_info['id']}`)\n\n"
                f"Available Models:\n{options}\n\n"
                f"Usage: `/model agb/<model-versi>`"
            )

    if lower.startswith("/new"):
        set_config("active_cid", "")
        parts = cmd.split(" ", 1)
        title = parts[1].strip() if len(parts) > 1 else ""
        return (
            f"New session prepared. "
            f"{('Title: ' + title) if title else 'Next prompt will create a brand new conversation.'}"
        )

    return None


def prepare_antigravity_dispatch(user_content: str, model_info: dict) -> tuple:
    """
    Thread-safe invocation of Antigravity CLI.
    Returns (cid, start_lines).
    """
    agentapi_cmd, use_shell = get_agentapi_cmd()
    model_id = model_info["id"]
    model_tier = model_info["tier"]
    brain = find_brain_dir()

    with SESSION_LOCK:
        cid = get_active_cid()
        if cid and not (brain / cid).is_dir():
            cid = ""

        if not cid:
            first_line = user_content.split("\n")[0].strip()
            clean_title = re.sub(r"[^\w\s-]", "", first_line)[:28].strip() or f"Hermes {time.strftime('%m-%d %H:%M')}"
            cmd = agentapi_cmd + [
                "new-conversation",
                f"--model={model_tier}",
                f"--title={model_info['name']}: {clean_title}",
                user_content
            ]
            log(f"Initializing single Antigravity session: '{clean_title}' with {model_info['name']}...")
            res = subprocess.run(cmd, capture_output=True, text=True, shell=use_shell)
            try:
                out = json.loads(res.stdout)
                cid = out.get("response", {}).get("newConversation", {}).get("conversationId")
                if cid:
                    set_active_cid(cid, f"{model_info['name']}: {clean_title}", model=model_id)
                    set_config("default_model", model_info["alt_id"])
            except Exception as e:
                log(f"Failed to parse new conversation response: {e}")
                increment_metric("total_errors", 1)
                return None, 0

            if not cid:
                increment_metric("total_errors", 1)
                return None, 0

            return cid, 0
        else:
            start_lines = get_transcript_line_count(cid)
            log(f"Sending message to persistent session {cid} ({model_info['name']})...")
            cmd = agentapi_cmd + ["send-message", cid, user_content]
            subprocess.run(cmd, capture_output=True, text=True, shell=use_shell)
            return cid, start_lines


def dispatch_prompt(user_content: str, requested_model: str = "", timeout: int = 60):
    """
    Dispatch prompt to Antigravity CLI for non-streaming requests.
    Thread-safe with deduplication to prevent double conversation creation.
    Returns: (reply_text, thinking_text, latency_ms, model_id)
    """
    t0 = time.time()

    cmd_response = handle_internal_command(user_content)
    if cmd_response is not None:
        latency_ms = int((time.time() - t0) * 1000)
        resolved_info = resolve_model(requested_model)
        return cmd_response, "", latency_ms, resolved_info["id"]

    model_info = resolve_model(requested_model)
    model_id = model_info["id"]

    req_hash = hashlib.sha256(f"{model_id}:{user_content}".encode("utf-8")).hexdigest()
    now = time.time()
    with SESSION_LOCK:
        if req_hash in RECENT_DISPATCHES:
            ts, cached_res = RECENT_DISPATCHES[req_hash]
            if now - ts < 4.0:
                log(f"Duplicate request detected within {now - ts:.2f}s. Debouncing to prevent double conversation.")
                return cached_res

    cid, start_lines = prepare_antigravity_dispatch(user_content, model_info)
    if not cid:
        return "Failed to initialize conversation session with Antigravity CLI.", "", 0, model_id

    reply, thinking, latency_ms = poll_for_response(cid, start_lines, timeout=timeout)
    if reply:
        record_history(cid, "user", user_content, 0)
        record_history(cid, "assistant", reply, latency_ms)
        increment_metric("total_requests", 1)
        increment_metric("total_tokens", len(user_content.split()) + len(reply.split()))
        log(f"Extracted response from CID {cid} in {latency_ms/1000:.2f}s ({len(reply)} chars)")
        result = (reply, thinking, latency_ms, model_id)
        with SESSION_LOCK:
            RECENT_DISPATCHES[req_hash] = (time.time(), result)
        return result

    log(f"Polling timeout on CID {cid}")
    increment_metric("total_errors", 1)
    timeout_ms = int((time.time() - t0) * 1000)
    timeout_result = ("Polling timeout reached on Antigravity Engine. Session remains intact in IDE.", "", timeout_ms, model_id)
    with SESSION_LOCK:
        RECENT_DISPATCHES[req_hash] = (time.time(), timeout_result)
    return timeout_result
