import sqlite3
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import config
from private_paths import validate_private_paths


@dataclass
class Capture:
    type: str
    raw: str
    title: Optional[str] = None
    url: Optional[str] = None
    event_dt: Optional[str] = None
    metadata: Optional[dict] = None
    id: Optional[int] = None
    created_at: Optional[str] = None


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    validate_private_paths([config.DB_PATH] + [Path(str(config.DB_PATH) + suffix)
                                            for suffix in ("-journal", "-wal", "-shm")])
    schema = (Path(__file__).parent / "schema.sql").read_text()
    with _connect() as conn:
        conn.executescript(schema)


def save(capture: Capture) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO captures (type, raw, title, url, event_dt, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                capture.type,
                capture.raw,
                capture.title,
                capture.url,
                capture.event_dt,
                json.dumps(capture.metadata) if capture.metadata else None,
            ),
        )
        return cur.lastrowid


def search(query: str, limit: int = 10) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM captures "
            "WHERE raw LIKE ? OR title LIKE ? "
            "ORDER BY created_at DESC LIMIT ?",
            (f"%{query}%", f"%{query}%", limit),
        ).fetchall()
    return [dict(r) for r in rows]


def recent(limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM captures ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
