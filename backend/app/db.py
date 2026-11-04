"""SQLite case history and admin statistics."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    language    TEXT    NOT NULL,
    question    TEXT    NOT NULL,
    file_name   TEXT,
    answer_json TEXT    NOT NULL,
    crisis_type TEXT,
    urgency     TEXT,
    not_found   INTEGER NOT NULL DEFAULT 0,
    latency_ms  INTEGER
)
"""

# Columns added after the first release; older databases are migrated on start-up.
MIGRATIONS = {
    "crisis_type": "ALTER TABLE cases ADD COLUMN crisis_type TEXT",
    "urgency": "ALTER TABLE cases ADD COLUMN urgency TEXT",
    "not_found": "ALTER TABLE cases ADD COLUMN not_found INTEGER NOT NULL DEFAULT 0",
    "latency_ms": "ALTER TABLE cases ADD COLUMN latency_ms INTEGER",
}


def _connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(SCHEMA)
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(cases)")}
        for column, sql in MIGRATIONS.items():
            if column not in existing:
                conn.execute(sql)
        # Back-fill denormalised columns for rows written by the first release.
        for row in conn.execute("SELECT id, answer_json FROM cases WHERE crisis_type IS NULL").fetchall():
            answer = json.loads(row["answer_json"])
            conn.execute(
                "UPDATE cases SET crisis_type = ?, urgency = ?, not_found = ? WHERE id = ?",
                (answer.get("crisis_type"), answer.get("urgency"), int(bool(answer.get("not_found"))), row["id"]),
            )


def save_case(
    language: str,
    question: str,
    file_name: str | None,
    answer: dict,
    latency_ms: int | None = None,
) -> int:
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO cases (created_at, language, question, file_name, answer_json, "
            "crisis_type, urgency, not_found, latency_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                language,
                question,
                file_name,
                json.dumps(answer, ensure_ascii=False),
                answer.get("crisis_type"),
                answer.get("urgency"),
                int(bool(answer.get("not_found"))),
                latency_ms,
            ),
        )
        return int(cur.lastrowid)


def _row_to_case(row: sqlite3.Row, full: bool) -> dict:
    case = {
        "id": row["id"],
        "created_at": row["created_at"],
        "language": row["language"],
        "question": row["question"],
        "file_name": row["file_name"],
        "crisis_type": row["crisis_type"],
        "urgency": row["urgency"],
        "not_found": bool(row["not_found"]),
        "latency_ms": row["latency_ms"],
    }
    if full:
        case["answer"] = json.loads(row["answer_json"])
    return case


def list_cases(limit: int = 20) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM cases ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_row_to_case(r, full=False) for r in rows]


def get_case(case_id: int) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    return _row_to_case(row, full=True) if row else None


def delete_case(case_id: int) -> bool:
    with closing(_connect()) as conn, conn:
        return conn.execute("DELETE FROM cases WHERE id = ?", (case_id,)).rowcount > 0


def _percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    values = sorted(values)
    index = min(len(values) - 1, max(0, round(pct / 100 * (len(values) - 1))))
    return values[index]


def _counts(conn: sqlite3.Connection, column: str) -> list[dict]:
    rows = conn.execute(
        f"SELECT COALESCE({column}, 'unknown') AS key, COUNT(*) AS count "
        f"FROM cases GROUP BY key ORDER BY count DESC, key"
    ).fetchall()
    return [{"key": r["key"], "count": r["count"]} for r in rows]


def stats(days: int = 14) -> dict:
    with closing(_connect()) as conn:
        total = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        not_found = conn.execute("SELECT COUNT(*) FROM cases WHERE not_found = 1").fetchone()[0]
        with_document = conn.execute("SELECT COUNT(*) FROM cases WHERE file_name IS NOT NULL").fetchone()[0]
        latencies = [
            r[0] for r in conn.execute("SELECT latency_ms FROM cases WHERE latency_ms IS NOT NULL")
        ]
        by_day_rows = conn.execute(
            "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count FROM cases GROUP BY day"
        ).fetchall()
        result = {
            "total_cases": total,
            "not_found_rate": round(not_found / total, 3) if total else 0.0,
            "with_document": with_document,
            "latency_ms": {
                "avg": round(sum(latencies) / len(latencies)) if latencies else None,
                "p50": _percentile(latencies, 50),
                "p95": _percentile(latencies, 95),
            },
            "by_crisis_type": _counts(conn, "crisis_type"),
            "by_urgency": _counts(conn, "urgency"),
            "by_language": _counts(conn, "language"),
        }

    # Fill in zero-count days so the chart has a continuous axis.
    counts = {r["day"]: r["count"] for r in by_day_rows}
    today = datetime.now(timezone.utc).date()
    result["per_day"] = [
        {"day": d.isoformat(), "count": counts.get(d.isoformat(), 0)}
        for d in (today - timedelta(days=i) for i in range(days - 1, -1, -1))
    ]
    return result
