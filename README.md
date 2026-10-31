# Antigravity Bridge

Universal OpenAI-compatible bridge connecting **Hermes Agent** with **Google Antigravity** models.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9+-brightgreen.svg)](https://python.org)
[![Hermes Compatible](https://img.shields.io/badge/Hermes-Compatible-orange.svg)](https://github.com/NousResearch/Hermes)
[![OpenAI API](https://img.shields.io/badge/API-OpenAI%20Compliant-purple.svg)](https://platform.openai.com/docs/api-reference)

---

## The Problem

Have you subscribed to Google Gemini Pro or Advanced with Antigravity installed, only to realize Hermes Agent cannot natively connect to it?

Antigravity provides access to flagship Gemini and Claude models through its desktop engine, but lacks an open standard API endpoint for third-party agents.

**Antigravity Bridge solves this.** It acts as a lightweight, zero-dependency translation layer that exposes an OpenAI-compatible HTTP and Server-Sent Events (SSE) streaming server (`/v1/chat/completions`) on port `8790`. It automatically captures reasoning (`thinking` blocks) and maps it to `reasoning_content`, preserving continuous conversation history without session fragmentation.

---

## Supported Models

The bridge strictly routes to the 4 official models available in Antigravity:

| Hermes Identifier | Model Name | Antigravity Engine Tier | Description |
| :--- | :--- | :--- | :--- |
| `agb/gemini-4-argon` | **Gemini 4 Argon** | `gemini-4-argon-high` | Google flagship high-intelligence reasoning model |
| `agb/gemini-3.8-flash` | **Gemini 3.8 flash** | `gemini-3.8-flash-high` | Ultra-fast low-latency high-throughput model |
| `agb/claude-opus-5.5` | **Claude Opus 5.5** | `claude-opus-5-5-high` | Premier deep architectural and complex coding model |
| `agb/claude-sonnet-5.5` | **Claude Sonnet 5.5** | `claude-sonnet-5-5-high` | Balanced high-precision development model |

---

## Quickstart (Zero Configuration)

### Method 1: Git Clone and Instant Init (Recommended)

```bash
git clone https://github.com/Muhammad-Rizqullah-Akbar/antigravity-bridge.git
cd antigravity-bridge
python init.py
```

`init.py` automatically:
1. Locates your Antigravity CLI installation (`agentapi` or `agy`).
2. Finds your Antigravity Brain storage directory.
3. Automatically patches `config.yaml` in your Hermes home and profiles to register provider `agb`.
4. Initializes a local SQLite ledger for state persistence.

### Method 2: Install via Pip

```bash
pip install git+https://github.com/Muhammad-Rizqullah-Akbar/antigravity-bridge.git
agb-connect
```

---

## Starting the Bridge

Start the server in the foreground:
```bash
agb start
```

Or run as a detached background daemon:
```bash
agb start --daemon
```

To stop the running bridge:
```bash
agb stop
```

To check real-time telemetry and health:
```bash
agb status
```

---

## Usage in Hermes (Telegram / Discord / Terminal)

Once the bridge is started and Hermes is running, switch models inside your chat client at any time:

```text
/model agb/gemini-4-argon
/model agb/gemini-3.8-flash
/model agb/claude-opus-5.5
/model agb/claude-sonnet-5.5
```

### In-Chat Commands

| Command | Action |
| :--- | :--- |
| `/model agb/<model-versi>` | Switch active model without breaking conversation history |
| `/status` | View connection health, uptime, active model, and session ID |
| `/list` | List recent conversation sessions in Antigravity Brain |
| `/attach <cid>` | Attach Hermes to an existing Antigravity session from your IDE |
| `/detach` | Unlink current session so next prompt starts a fresh conversation |
| `/new [title]` | Immediately create a new independent conversation |
| `/help` | Display command guide |

---

## Hermes Configuration Reference

If you prefer manual configuration, add the following snippet to your `~/.hermes/config.yaml` or `%LOCALAPPDATA%\hermes\config.yaml`:

```yaml
providers:
  agb:
    base_url: http://127.0.0.1:8790/v1
    api_key: sovereign-antigravity-key
    discover_models: true
    models:
      - agb/gemini-4-argon
      - agb/gemini-3.8-flash
      - agb/claude-opus-5.5
      - agb/claude-sonnet-5.5

model: agb/gemini-4-argon
```

---

## Architecture

```
+-------------------------------------------------------------+
|                        Hermes Agent                         |
|             (Telegram, Discord, Terminal Client)            |
+-------------------------------------------------------------+
                              |
                     HTTP / SSE Streaming
                              v
+-------------------------------------------------------------+
|                 Antigravity Bridge (Port 8790)              |
|                                                             |
|  * OpenAI-Compatible Server (/v1/chat/completions)          |
|  * Reasoning Content Extraction (thinking -> reasoning)    |
|  * Zero Session Splitting History Ledger (SQLite)           |
|  * Real-Time Transcript Tailer & Artifact Discovery         |
+-------------------------------------------------------------+
                              |
                    IPC Process Dispatcher
                              v
+-------------------------------------------------------------+
|             Google Antigravity Engine (agentapi)            |
|       [Gemini 4 Argon / 3.8 Flash / Claude 5.5 Family]       |
+-------------------------------------------------------------+
```

---

## Key Highlights

- **Native Reasoning Extraction**: Antigravity internal `thinking` blocks are converted directly into OpenAI `reasoning_content` delta tokens.
- **Zero Session Splitting**: Switching models preserves the full conversation transcript without resetting conversation ID.
- **Artifact Discovery**: Files or code artifacts generated by Antigravity in the background are automatically announced in chat responses.
- **Zero Heavy Dependencies**: Built entirely with Python standard library. No torch, no heavy frameworks, fast startup in under 0.05 seconds.

---

## License

This project is licensed under the [MIT License](LICENSE).
Created with precision by Muhammad Rizqullah Akbar.
