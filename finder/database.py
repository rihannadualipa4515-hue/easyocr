"""SQLite storage. Table `captured_text` is the equivalent of the CapturedText model."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .errors import StorageError
from .services.text_processor import fold_word

SCHEMA = """
CREATE TABLE IF NOT EXISTS captured_text (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    original_text TEXT NOT NULL DEFAULT '',
    cleaned_text  TEXT NOT NULL DEFAULT '',
    screenshot    TEXT,
    match_mode    TEXT NOT NULL DEFAULT 'all',
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS found_sentence (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id  INTEGER NOT NULL REFERENCES captured_text(id) ON DELETE CASCADE,
    line_number INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    sentence    TEXT NOT NULL,
    is_best     INTEGER NOT NULL DEFAULT 0,
    score       REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_found_capture ON found_sentence(capture_id);
CREATE INDEX IF NOT EXISTS idx_captured_created ON captured_text(created_at);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(found_sentence)")}
            for name, ddl in (("is_best", "INTEGER NOT NULL DEFAULT 0"), ("score", "REAL NOT NULL DEFAULT 0")):
                if name not in cols:                       # database created by an older version
                    conn.execute(f"ALTER TABLE found_sentence ADD COLUMN {name} {ddl}")

    @contextmanager
    def _conn(self):
        try:
            conn = sqlite3.connect(self.path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.create_function("fold", 1, lambda v: fold_word(v or ""))
        except sqlite3.Error as exc:
            raise StorageError(f"Cannot open the database: {exc}") from exc
        try:
            with conn:                      # commit / rollback
                yield conn
        except sqlite3.Error as exc:
            raise StorageError(f"Database error: {exc}") from exc
        finally:
            conn.close()

    def add_capture(self, original: str, cleaned: str, screenshot: str | None,
                    mode: str, matches: list[tuple[int, int, str]],
                    answers: list[tuple[int, int, str, float]] = ()) -> int:
        """matches: (line_number, position, sentence); answers: (line_number, position, sentence, score)."""
        created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO captured_text (original_text, cleaned_text, screenshot, match_mode, created_at)"
                " VALUES (?,?,?,?,?)", (original, cleaned, screenshot, mode, created))
            capture_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO found_sentence (capture_id, line_number, position, sentence) VALUES (?,?,?,?)",
                [(capture_id, ln, pos, s) for ln, pos, s in matches])
            conn.executemany(
                "INSERT INTO found_sentence (capture_id, line_number, position, sentence, is_best, score)"
                " VALUES (?,?,?,?,1,?)", [(capture_id, ln, pos, s, sc) for ln, pos, s, sc in answers])
        return capture_id

    def list_captures(self, query: str = "", limit: int = 500) -> list[sqlite3.Row]:
        sql = ("SELECT c.*, (SELECT COUNT(*) FROM found_sentence f WHERE f.capture_id = c.id AND f.is_best = 0) AS match_count"
               " FROM captured_text c")
        params: list = []
        query = query.strip()
        if query:
            folded = fold_word(query)
            like = "%" + folded.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            sql += (" WHERE fold(c.original_text) LIKE ? ESCAPE '\\' OR fold(c.cleaned_text) LIKE ? ESCAPE '\\'"
                    " OR c.id IN (SELECT capture_id FROM found_sentence WHERE fold(sentence) LIKE ? ESCAPE '\\')")
            params += [like, like, like]
        sql += " ORDER BY c.id DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            return conn.execute(sql, params).fetchall()

    def get_capture(self, capture_id: int) -> sqlite3.Row | None:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM captured_text WHERE id=?", (capture_id,)).fetchone()

    def get_matches(self, capture_id: int) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT line_number, position, sentence, is_best, score FROM found_sentence WHERE capture_id=? ORDER BY id",
                (capture_id,)).fetchall()

    def delete_capture(self, capture_id: int) -> str | None:
        """Deletes the record, returns the stored screenshot path (so the caller can remove the file)."""
        with self._conn() as conn:
            row = conn.execute("SELECT screenshot FROM captured_text WHERE id=?", (capture_id,)).fetchone()
            conn.execute("DELETE FROM captured_text WHERE id=?", (capture_id,))
        return row["screenshot"] if row else None
