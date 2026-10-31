"""
Database management and telemetry ledger for Antigravity Bridge.
"""

import sqlite3
import time
import os
from pathlib import Path
from antigravity_bridge.config import get_db_path, get_logs_dir

LOG_FILE = get_logs_dir() / "bridge.log"


def log(msg: str):
    """Write message to timestamped log file and stdout."""
    t_str = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{t_str}] {msg}"
    print(entry)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def get_connection():
    """Create a thread-safe connection to SQLite with WAL mode."""
    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path), timeout=15.0)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def init_db():
    """Initialize SQLite database tables if not existing."""
    conn = get_connection()
    try:
        with conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS bridge_config (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at REAL
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                cid TEXT PRIMARY KEY,
                title TEXT,
                model TEXT,
                created_at REAL,
                last_used_at REAL
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cid TEXT,
                role TEXT,
                content TEXT,
                latency_ms INTEGER,
                created_at REAL
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                key TEXT PRIMARY KEY,
                value INTEGER
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cid TEXT,
                filename TEXT,
                file_path TEXT,
                file_size INTEGER,
                discovered_at REAL
            );
            """)

            # Seed default metrics
            for k in ("total_requests", "total_tokens", "total_errors"):
                conn.execute("INSERT OR IGNORE INTO metrics (key, value) VALUES (?, 0);", (k,))
    finally:
        conn.close()


def get_config(key: str, default: str = "") -> str:
    """Retrieve configuration string."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM bridge_config WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else default
    finally:
        conn.close()


def set_config(key: str, value: str):
    """Save configuration string."""
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO bridge_config (key, value, updated_at) VALUES (?, ?, ?)",
                (key, str(value), time.time())
            )
    finally:
        conn.close()


def get_active_cid() -> str:
    """Retrieve currently bound conversation ID."""
    return get_config("active_cid", "")


def set_active_cid(cid: str, title: str = "", model: str = ""):
    """Persist the active conversation ID and record session."""
    set_config("active_cid", cid)
    if cid:
        conn = get_connection()
        try:
            now = time.time()
            with conn:
                conn.execute("""
                INSERT INTO sessions (cid, title, model, created_at, last_used_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cid) DO UPDATE SET
                    title = CASE WHEN ? != '' THEN ? ELSE title END,
                    model = CASE WHEN ? != '' THEN ? ELSE model END,
                    last_used_at = ?
                """, (cid, title or "Session", model or "default", now, now,
                      title, title, model, model, now))
        finally:
            conn.close()


def record_history(cid: str, role: str, content: str, latency_ms: int = 0):
    """Record an interaction entry in history."""
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO history (cid, role, content, latency_ms, created_at) VALUES (?, ?, ?, ?, ?)",
                (cid, role, content, latency_ms, time.time())
            )
    finally:
        conn.close()


def record_artifact(cid: str, filename: str, file_path: str, file_size: int):
    """Record an artifact discovered in session."""
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO artifacts (cid, filename, file_path, file_size, discovered_at) VALUES (?, ?, ?, ?, ?)",
                (cid, filename, file_path, file_size, time.time())
            )
    finally:
        conn.close()


def increment_metric(key: str, amount: int = 1):
    """Increment numeric metric in ledger."""
    conn = get_connection()
    try:
        with conn:
            conn.execute("""
            INSERT INTO metrics (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = value + ?
            """, (key, amount, amount))
    finally:
        conn.close()


def get_telemetry_stats() -> dict:
    """Retrieve telemetry metrics."""
    conn = get_connection()
    stats = {"total_requests": 0, "total_tokens": 0, "total_errors": 0}
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM metrics")
        for k, v in cur.fetchall():
            if k in stats:
                stats[k] = v
    finally:
        conn.close()
    return stats
