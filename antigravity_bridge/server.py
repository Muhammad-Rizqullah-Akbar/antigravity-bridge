import http.server
import socketserver
import json
import time
import uuid
import traceback
import subprocess
import os
import re
import threading
import hashlib

from config import (
    HOST, PORT, SERVER_VERSION, SERVER_NAME,
    AGENTAPI_PATH, GEMINI_BRAIN_DIR, LANGUAGE_SERVER_PATH,
    get_agentapi_cmd
)
from auth import validate_request_auth
from db import (
    log, get_active_cid, set_active_cid, get_config, set_config,
    record_history, increment_metric, get_telemetry_stats, get_session_model
)
from tailer import (
    get_transcript_line_count, poll_for_response, stream_tokens_from_text,
    live_stream_transcript
)
from commands import handle_telegram_command, list_brain_sessions

START_TIME = time.time()
SESSION_LOCK = threading.Lock()
RECENT_DISPATCHES = {}

OFFICIAL_MODELS = {
    "gemini-4-argon": {
        "id": "agb/gemini-4-argon",
        "alt_id": "gemini-4-argon",
        "name": "Gemini 4 Argon",
        "tier": "gemini-4-argon-high",
        "desc": "Google DeepMind Next-Gen Frontier Architecture"
    },
    "gemini-3.8-flash": {
        "id": "agb/gemini-3.8-flash",
        "alt_id": "gemini-3.8-flash",
        "name": "Gemini 3.8 flash",
        "tier": "gemini-3.8-flash-high",
        "desc": "Ultra-Fast Frontier Flash Engine"
    },
    "claude-opus-5.5": {
        "id": "agb/claude-opus-5.5",
        "alt_id": "claude-opus-5.5",
        "name": "Claude Opus 5.5",
        "tier": "claude-opus-5-5-high",
        "desc": "Anthropic Apex Intelligence & Deep Complex Reasoning"
    },
    "claude-sonnet-5.5": {
        "id": "agb/claude-sonnet-5.5",
        "alt_id": "claude-sonnet-5.5",
        "name": "Claude Sonnet 5.5",
        "tier": "claude-sonnet-5-5-high",
        "desc": "Anthropic Advanced Coding & Systems Engineering"
    }
}

DEFAULT_MODEL_KEY = "gemini-4-argon"


def resolve_model(raw_name):
    clean = str(raw_name or "").lower().strip().replace("agb/", "")
    if "argon" in clean or "gemini-4" in clean:
        return OFFICIAL_MODELS["gemini-4-argon"]
    elif "opus" in clean:
        return OFFICIAL_MODELS["claude-opus-5.5"]
    elif "sonnet" in clean:
        return OFFICIAL_MODELS["claude-sonnet-5.5"]
    elif "flash" in clean or "3.8" in clean:
        return OFFICIAL_MODELS["gemini-3.8-flash"]

    cfg_key = get_config("default_model", DEFAULT_MODEL_KEY)
    return OFFICIAL_MODELS.get(cfg_key, OFFICIAL_MODELS[DEFAULT_MODEL_KEY])


def extract_clean_prompt(messages):
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
        clean_user = raw_user_content.strip() or "Halo Mr. Robot"

    return clean_user, system_text


def prepare_antigravity_dispatch(user_content, model_info):
    """
    Thread-safe invocation of Antigravity CLI.
    Returns (cid, start_lines).
    """
    agentapi_cmd = get_agentapi_cmd()
    use_shell = False if os.path.exists(LANGUAGE_SERVER_PATH) else True
    active_tier = model_info["tier"]
    model_id = model_info["id"]

    with SESSION_LOCK:
        cid = get_active_cid()
        if cid and not os.path.exists(os.path.join(GEMINI_BRAIN_DIR, cid)):
            cid = ""

        if not cid:
            first_line = user_content.split("\n")[0].strip()
            clean_title = re.sub(r"[^\w\s-]", "", first_line)[:28].strip() or f"Hermes {time.strftime('%m-%d %H:%M')}"
            title_arg = f"--title={model_info['name']}: {clean_title}"

            cmd = agentapi_cmd + ["new-conversation", f"--model={active_tier}", title_arg, user_content]
            log(f"Inisialisasi sesi tunggal: '{clean_title}' (Model: {model_info['name']})...")
            res = subprocess.run(cmd, capture_output=True, text=True, shell=use_shell)
            try:
                out = json.loads(res.stdout)
                cid = out.get("response", {}).get("newConversation", {}).get("conversationId")
                if cid:
                    set_active_cid(cid, f"{model_info['name']}: {clean_title}", model=model_id)
                    set_config("default_model", model_id)
            except Exception as e:
                log(f"Gagal membuat sesi: {e}")
                increment_metric("total_errors", 1)
                return None, 0

            if not cid:
                increment_metric("total_errors", 1)
                return None, 0

            return cid, 0
        else:
            start_lines = get_transcript_line_count(cid)
            log(f"Melanjutkan sesi persisten {cid} (Model: {model_info['name']}, baris: {start_lines})...")
            cmd = agentapi_cmd + ["send-message", cid, user_content]
            subprocess.run(cmd, capture_output=True, text=True, shell=use_shell)
            return cid, start_lines


def dispatch_prompt_to_antigravity(user_content, requested_model="", timeout=60):
    """Synchronous fallback for non-streaming requests."""
    t0 = time.time()
    stripped = user_content.strip()

    cmd_response = handle_telegram_command(stripped)
    if cmd_response:
        increment_metric("total_requests", 1)
        return cmd_response, "", int((time.time() - t0) * 1000), get_config("default_model", DEFAULT_MODEL_KEY)

    model_info = resolve_model(requested_model or get_config("default_model", DEFAULT_MODEL_KEY))
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
        return "SAYA Mr. Robot HAIL XENONITE!. Gagal memperoleh ID Sesi Antigravity Brain.", "", 0, model_id

    reply, thinking, latency_ms = poll_for_response(cid, start_lines, timeout=timeout)
    if reply:
        record_history(cid, "user", user_content, 0)
        record_history(cid, "assistant", reply, latency_ms)
        increment_metric("total_requests", 1)
        increment_metric("total_tokens", len(user_content.split()) + len(reply.split()))
        log(f"Respons terekstraksi dari CID {cid} dalam {latency_ms/1000:.2f}s ({len(reply)} chars)")
        result = (reply, thinking, latency_ms, model_id)
        with SESSION_LOCK:
            RECENT_DISPATCHES[req_hash] = (time.time(), result)
        return result

    log(f"Timeout pada CID: {cid}")
    increment_metric("total_errors", 1)
    timeout_result = (
        "SAYA Mr. Robot HAIL XENONITE!, HAIL XENONITE!, HAIL XENONITE!. MAESTRO, batas waktu polling tercapai di Antigravity. Riwayat sesi tetap terjaga di IDE.",
        "",
        int((time.time() - t0) * 1000),
        model_id
    )
    with SESSION_LOCK:
        RECENT_DISPATCHES[req_hash] = (time.time(), timeout_result)
    return timeout_result


class ThreadingTitaniumServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class TitaniumHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if self.path.startswith("/v1/"):
                auth_ok, auth_err = validate_request_auth(self.headers)
                if not auth_ok:
                    self.send_error_response(auth_err, 401)
                    return

            if self.path in ("/v1/models", "/models"):
                items = []
                for m in OFFICIAL_MODELS.values():
                    items.append({
                        "id": m["id"],
                        "object": "model",
                        "created": int(START_TIME),
                        "owned_by": "antigravity",
                        "description": f"{m['name']} ({m['desc']})"
                    })
                    items.append({
                        "id": m["alt_id"],
                        "object": "model",
                        "created": int(START_TIME),
                        "owned_by": "antigravity",
                        "description": f"{m['name']} ({m['desc']})"
                    })
                self.send_json_response({"object": "list", "data": items})
            elif self.path in ("/health", "/healthz"):
                cid = get_active_cid()
                cur_model = get_config("default_model", DEFAULT_MODEL_KEY)
                m_info = OFFICIAL_MODELS.get(cur_model, OFFICIAL_MODELS[DEFAULT_MODEL_KEY])
                uptime_sec = int(time.time() - START_TIME)
                stats = get_telemetry_stats()
                self.send_json_response({
                    "status": "healthy",
                    "version": SERVER_VERSION,
                    "service": SERVER_NAME,
                    "active_session": cid,
                    "active_model": m_info["name"],
                    "available_models": [m["name"] for m in OFFICIAL_MODELS.values()],
                    "uptime_seconds": uptime_sec,
                    "telemetry": stats
                })
            elif self.path == "/sessions":
                sessions = list_brain_sessions(15)
                self.send_json_response({"sessions": sessions})
            elif self.path in ("/dashboard", "/"):
                self.send_dashboard_response()
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            log(f"GET error: {e}")

    def do_POST(self):
        try:
            if self.path in ("/v1/chat/completions", "/chat/completions"):
                auth_ok, auth_err = validate_request_auth(self.headers)
                if not auth_ok:
                    self.send_error_response(auth_err, 401)
                    return

                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                data = json.loads(body)
                messages = data.get("messages", [])
                stream = data.get("stream", False)
                requested_model = data.get("model", "")

                user_content, system_guidance = extract_clean_prompt(messages)
                completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

                # 1. Telegram Command Interception
                cmd_response = handle_telegram_command(user_content.strip())
                if cmd_response:
                    increment_metric("total_requests", 1)
                    if stream:
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        for chunk_data in stream_tokens_from_text(cmd_response, completion_id, model_name=requested_model or DEFAULT_MODEL_KEY):
                            self.wfile.write(chunk_data.encode("utf-8"))
                            self.wfile.flush()
                    else:
                        resp_payload = {
                            "id": completion_id,
                            "object": "chat.completion",
                            "created": int(time.time()),
                            "model": requested_model or DEFAULT_MODEL_KEY,
                            "choices": [{"index": 0, "message": {"role": "assistant", "content": cmd_response}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": len(user_content.split()), "completion_tokens": len(cmd_response.split()), "total_tokens": len(user_content.split()) + len(cmd_response.split())}
                        }
                        self.send_json_response(resp_payload)
                    return

                # 2. Model Selection
                model_info = resolve_model(requested_model or get_config("default_model", DEFAULT_MODEL_KEY))
                model_id = model_info["id"]

                # 3. Execution: True Live Streaming vs JSON Non-Streaming
                log(f"Menerima request /v1/chat/completions (stream={stream}, model={model_id})")
                if stream:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()

                    cid, start_lines = prepare_antigravity_dispatch(user_content, model_info)
                    if not cid:
                        err_msg = "SAYA Mr. Robot HAIL XENONITE!. Gagal menginisialisasi sesi percakapan di Antigravity Brain."
                        for c in stream_tokens_from_text(err_msg, completion_id, model_name=model_id):
                            self.wfile.write(c.encode("utf-8"))
                            self.wfile.flush()
                        return

                    t0 = time.time()
                    log(f"Stream live dimulai untuk CID {cid} (Model: {model_id})...")
                    generator = live_stream_transcript(cid, start_lines, completion_id, model_name=model_id, timeout=65)
                    full_reply_parts = []
                    try:
                        for chunk_str in generator:
                            self.wfile.write(chunk_str.encode("utf-8"))
                            self.wfile.flush()
                            if chunk_str.startswith("data: ") and not chunk_str.startswith("data: [DONE]"):
                                try:
                                    c_json = json.loads(chunk_str[6:].strip())
                                    delta = c_json.get("choices", [{}])[0].get("delta", {})
                                    txt = delta.get("content", "")
                                    if txt:
                                        full_reply_parts.append(txt)
                                except Exception:
                                    pass
                    except (BrokenPipeError, ConnectionResetError):
                        log("Client disconnected during live streaming.")

                    total_text = "".join(full_reply_parts)
                    latency_ms = int((time.time() - t0) * 1000)
                    if total_text:
                        record_history(cid, "user", user_content, 0)
                        record_history(cid, "assistant", total_text, latency_ms)
                        increment_metric("total_tokens", len(user_content.split()) + len(total_text.split()))
                        log(f"Stream live selesai untuk CID {cid} dalam {latency_ms/1000:.2f}s ({len(total_text)} chars)")
                    increment_metric("total_requests", 1)
                else:
                    assistant_reply, thinking, latency_ms, active_model_id = dispatch_prompt_to_antigravity(
                        user_content, requested_model=requested_model
                    )
                    message_payload = {
                        "role": "assistant",
                        "content": assistant_reply
                    }
                    if thinking and thinking.strip():
                        message_payload["reasoning_content"] = thinking

                    resp_payload = {
                        "id": completion_id,
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": active_model_id,
                        "choices": [
                            {
                                "index": 0,
                                "message": message_payload,
                                "finish_reason": "stop"
                            }
                        ],
                        "usage": {
                            "prompt_tokens": len(user_content.split()),
                            "completion_tokens": len(assistant_reply.split()),
                            "total_tokens": len(user_content.split()) + len(assistant_reply.split())
                        }
                    }
                    self.send_json_response(resp_payload)
            elif self.path == "/shutdown":
                self.send_json_response({"message": "Server shutting down..."})
                threading.Thread(target=self.server.shutdown).start()
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            log(f"POST error: {e}\n{traceback.format_exc()}")
            increment_metric("total_errors", 1)
            self.send_error_response(str(e))

    def send_json_response(self, data, code=200):
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        except Exception as e:
            log(f"Socket send error: {e}")

    def send_error_response(self, message, code=500):
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": message, "type": "titanium_bridge_error"}}).encode("utf-8"))
        except Exception as e:
            log(f"Socket error response failed: {e}")

    def send_dashboard_response(self):
        cid = get_active_cid() or "None"
        cur_model = get_config("default_model", DEFAULT_MODEL_KEY)
        m_info = OFFICIAL_MODELS.get(cur_model, OFFICIAL_MODELS[DEFAULT_MODEL_KEY])
        uptime = int(time.time() - START_TIME)
        stats = get_telemetry_stats()

        models_html = "".join([
            f"<div style='border: 1px solid #334155; padding: 12px; margin-bottom: 8px; border-radius: 6px;'>"
            f"<b>{m['name']}</b> (<code>{m['id']}</code>)<br>"
            f"<span style='color: #94a3b8; font-size: 13px;'>{m['desc']}</span><br>"
            f"<span style='color: #38bdf8; font-size: 12px;'>Tier: <code>{m['tier']}</code></span>"
            f"</div>"
            for m in OFFICIAL_MODELS.values()
        ])

        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Titanium Sovereign Bridge v{SERVER_VERSION}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0b0f19; color: #f1f5f9; padding: 24px; }}
.card {{ background: #131c2e; border: 1px solid #1e293b; border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
h1 {{ color: #38bdf8; margin-top: 0; }}
code {{ background: #0f172a; padding: 2px 6px; border-radius: 4px; }}
</style>
</head>
<body>
<h1>{SERVER_NAME}</h1>
<div class="card">
<p><b>Status:</b> ONLINE | <b>Version:</b> {SERVER_VERSION}</p>
<p><b>Active Model:</b> {m_info['name']} (<code>{m_info['id']}</code>)</p>
<p><b>Active Antigravity Session:</b> <code>{cid}</code></p>
<p><b>Uptime:</b> {uptime}s | <b>Interactions:</b> {stats['total_requests']} | <b>Tokens:</b> {stats['total_tokens']}</p>
</div>
<h2>Available Official Models</h2>
{models_html}
</body>
</html>"""
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        except Exception as e:
            log(f"Dashboard send error: {e}")

    def log_message(self, format, *args):
        pass


def run_titanium_server(host=HOST, port=PORT):
    server_address = (host, port)
    httpd = ThreadingTitaniumServer(server_address, TitaniumHandler)
    log(f"Starting {SERVER_NAME} v{SERVER_VERSION} on {host}:{port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("Server dihentikan manual.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run_titanium_server()
