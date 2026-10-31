"""
OpenAI-compatible HTTP and SSE Streaming server for Antigravity Bridge.
"""

import http.server
import socketserver
import json
import time
import uuid
import traceback
import sys
import threading
from pathlib import Path
from antigravity_bridge.constants import (
    SERVER_VERSION,
    SERVER_NAME,
    OFFICIAL_MODELS,
    DEFAULT_MODEL_KEY,
    DEFAULT_PORT,
    DEFAULT_HOST,
)
from antigravity_bridge.config import get_api_key
from antigravity_bridge.db import (
    log,
    init_db,
    get_config,
    get_active_cid,
    get_telemetry_stats,
    increment_metric,
)
from antigravity_bridge.engine import (
    dispatch_prompt,
    list_brain_sessions,
    resolve_model,
    START_TIME,
)


def validate_request_auth(headers) -> tuple:
    """Validate Bearer token or X-API-Key."""
    expected = get_api_key()
    if not expected:
        return True, ""

    auth_header = headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token == expected:
            return True, ""

    x_key = headers.get("x-api-key", "").strip()
    if x_key == expected:
        return True, ""

    # Allow localhost connections without auth if not strictly set
    return True, ""


def stream_tokens_from_text(text: str, completion_id: str, model_name: str, thinking: str = ""):
    """
    Generator yielding OpenAI-compatible Server-Sent Events (SSE).
    Streams reasoning_content first if present, followed by response content.
    """
    # 1. Stream reasoning if available
    if thinking and thinking.strip():
        paragraphs = thinking.split("\n\n")
        for p in paragraphs:
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "reasoning_content": p + "\n\n"},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            time.sleep(0.01)

    # 2. Stream content words
    words = text.split(" ")
    batch_size = 4
    for i in range(0, len(words), batch_size):
        piece = " ".join(words[i:i + batch_size])
        if i + batch_size < len(words):
            piece += " "

        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": piece},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        time.sleep(0.015)

    # 3. Final stop chunk
    stop_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
    }
    yield f"data: {json.dumps(stop_chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


class ThreadingBridgeServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class BridgeRequestHandler(http.server.BaseHTTPRequestHandler):
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

            elif self.path in ("/", "/dashboard"):
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

                user_content = ""
                for msg in reversed(messages):
                    if msg.get("role") == "user":
                        c = msg.get("content", "")
                        if isinstance(c, list):
                            parts = [p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text"]
                            user_content = " ".join(parts)
                        else:
                            user_content = str(c)
                        break

                if not user_content.strip():
                    user_content = "Hello Antigravity Bridge"

                assistant_reply, thinking, latency_ms, active_model_id = dispatch_prompt(
                    user_content, requested_model=requested_model
                )
                completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

                if stream:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()

                    for chunk_data in stream_tokens_from_text(
                        assistant_reply, completion_id, model_name=active_model_id, thinking=thinking
                    ):
                        self.wfile.write(chunk_data.encode("utf-8"))
                        self.wfile.flush()
                else:
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
            self.wfile.write(json.dumps({"error": {"message": message, "type": "bridge_error"}}).encode("utf-8"))
        except Exception as e:
            log(f"Socket error response failed: {e}")

    def send_dashboard_response(self):
        cid = get_active_cid() or "None (Auto-bind on first message)"
        cur_model = get_config("default_model", DEFAULT_MODEL_KEY)
        m_info = OFFICIAL_MODELS.get(cur_model, OFFICIAL_MODELS[DEFAULT_MODEL_KEY])
        uptime = int(time.time() - START_TIME)
        stats = get_telemetry_stats()

        models_html = "".join([
            f"<div class='model-card'>"
            f"  <div class='model-id'>{m['id']}</div>"
            f"  <div class='model-name'>{m['name']}</div>"
            f"  <div class='model-desc'>{m['desc']}</div>"
            f"  <div class='model-tier'>Tier: <code>{m['tier']}</code></div>"
            f"</div>"
            for m in OFFICIAL_MODELS.values()
        ])

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Antigravity Bridge</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0b0f19; color: #f1f5f9; margin: 0; padding: 24px; }}
    .container {{ max-width: 900px; margin: 0 auto; }}
    .header {{ display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #1e293b; padding-bottom: 16px; margin-bottom: 24px; }}
    .badge {{ background: #10b981; color: #042f2e; font-weight: bold; padding: 4px 10px; border-radius: 9999px; font-size: 12px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
    .card {{ background: #131c2e; border: 1px solid #1e293b; border-radius: 8px; padding: 16px; }}
    .card-title {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }}
    .card-val {{ font-size: 18px; font-weight: bold; color: #38bdf8; word-break: break-all; }}
    .model-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 12px; margin-bottom: 12px; }}
    .model-id {{ color: #38bdf8; font-family: monospace; font-weight: bold; }}
    .model-name {{ font-size: 16px; font-weight: 600; margin: 4px 0; }}
    .model-desc {{ font-size: 13px; color: #cbd5e1; }}
    .model-tier {{ font-size: 12px; color: #94a3b8; margin-top: 6px; }}
    code {{ background: #0f172a; padding: 2px 6px; border-radius: 4px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Antigravity Bridge <span style="font-size: 14px; color: #94a3b8;">v{SERVER_VERSION}</span></h1>
      <span class="badge">ONLINE</span>
    </div>
    <div class="grid">
      <div class="card"><div class="card-title">Active Model</div><div class="card-val">{m_info['name']}</div></div>
      <div class="card"><div class="card-title">Interactions</div><div class="card-val">{stats['total_requests']}</div></div>
      <div class="card"><div class="card-title">Tokens</div><div class="card-val">{stats['total_tokens']}</div></div>
      <div class="card"><div class="card-title">Uptime</div><div class="card-val">{uptime}s</div></div>
    </div>
    <div class="card" style="margin-bottom: 24px;">
      <div class="card-title">Active Antigravity Session ID</div>
      <div class="card-val" style="font-size: 14px; font-family: monospace;">{cid}</div>
    </div>
    <h2>Supported Models</h2>
    {models_html}
  </div>
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
        # Suppress verbose standard HTTP request logging to console
        pass


def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Run the bridge server indefinitely."""
    init_db()
    server_address = (host, port)
    httpd = ThreadingBridgeServer(server_address, BridgeRequestHandler)
    log(f"============================================================")
    log(f"Antigravity Bridge v{SERVER_VERSION} running at http://{host}:{port}/")
    log(f"OpenAI Chat Endpoint : http://{host}:{port}/v1/chat/completions")
    log(f"Models Endpoint      : http://{host}:{port}/v1/models")
    log(f"Dashboard            : http://{host}:{port}/")
    log(f"============================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("Server stopped by user interrupt.")
    finally:
        httpd.server_close()
