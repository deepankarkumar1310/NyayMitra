"""SQLite case history."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    language    TEXT    NOT NULL,
    question    TEXT    NOT NULL,
    file_name   TEXT,
    answer_json TEXT    NOT NULL
)
"""


def _connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(SCHEMA)


def save_case(language: str, question: str, file_name: str | None, answer: dict) -> int:
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO cases (created_at, language, question, file_name, answer_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                language,
                question,
                file_name,
                json.dumps(answer, ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid)


def _row_to_case(row: sqlite3.Row, full: bool) -> dict:
    answer = json.loads(row["answer_json"])
    case = {
        "id": row["id"],
        "created_at": row["created_at"],
        "language": row["language"],
        "question": row["question"],
        "file_name": row["file_name"],
        "crisis_type": answer.get("crisis_type"),
        "urgency": answer.get("urgency"),
    }
    if full:
        case["answer"] = answer
    return case


def list_cases(limit: int = 20) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM cases ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_case(r, full=False) for r in rows]


def get_case(case_id: int) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    return _row_to_case(row, full=True) if row else None
