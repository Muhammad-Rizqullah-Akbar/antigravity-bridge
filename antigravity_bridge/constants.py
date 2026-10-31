"""
Constants and model definitions for Antigravity Bridge.
"""

SERVER_VERSION = "1.0.0"
SERVER_NAME = "Antigravity Bridge Server"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8790
DEFAULT_API_KEY = "sovereign-antigravity-key"

# Official Antigravity models supported by the bridge
OFFICIAL_MODELS = {
    "gemini-4-argon": {
        "id": "agb/gemini-4-argon",
        "alt_id": "gemini-4-argon",
        "tier": "gemini-4-argon-high",
        "name": "Gemini 4 Argon",
        "desc": "Google flagship high-intelligence reasoning model",
    },
    "gemini-3.8-flash": {
        "id": "agb/gemini-3.8-flash",
        "alt_id": "gemini-3.8-flash",
        "tier": "gemini-3.8-flash-high",
        "name": "Gemini 3.8 flash",
        "desc": "Ultra-fast low-latency high-throughput model",
    },
    "claude-opus-5.5": {
        "id": "agb/claude-opus-5.5",
        "alt_id": "claude-opus-5.5",
        "tier": "claude-opus-5-5-high",
        "name": "Claude Opus 5.5",
        "desc": "Premier deep architectural and complex coding model",
    },
    "claude-sonnet-5.5": {
        "id": "agb/claude-sonnet-5.5",
        "alt_id": "claude-sonnet-5.5",
        "tier": "claude-sonnet-5-5-high",
        "name": "Claude Sonnet 5.5",
        "desc": "Balanced high-precision development model",
    },
}

DEFAULT_MODEL_KEY = "gemini-4-argon"

# Quick lookup mapping for model resolution
MODEL_LOOKUP = {
    "agb/gemini-4-argon": "gemini-4-argon",
    "gemini-4-argon": "gemini-4-argon",
    "gemini-4": "gemini-4-argon",
    "argon": "gemini-4-argon",

    "agb/gemini-3.8-flash": "gemini-3.8-flash",
    "gemini-3.8-flash": "gemini-3.8-flash",
    "gemini-flash": "gemini-3.8-flash",
    "flash": "gemini-3.8-flash",

    "agb/claude-opus-5.5": "claude-opus-5.5",
    "claude-opus-5.5": "claude-opus-5.5",
    "claude-opus": "claude-opus-5.5",
    "opus": "claude-opus-5.5",

    "agb/claude-sonnet-5.5": "claude-sonnet-5.5",
    "claude-sonnet-5.5": "claude-sonnet-5.5",
    "claude-sonnet": "claude-sonnet-5.5",
    "sonnet": "claude-sonnet-5.5",
}
