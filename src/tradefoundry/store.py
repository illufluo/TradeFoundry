"""SQLite 追加式实验记录；保存完整可复现输入和结果。"""

import hashlib
import json
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


def encode(value) -> str:
    return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False, allow_nan=False)


def code_revision() -> str:
    try:
        root = Path(__file__).resolve().parents[2]
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root, text=True
        ).strip()
        return sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown-installed-package"


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                status TEXT NOT NULL, payload TEXT NOT NULL
            )""")

    @contextmanager
    def connect(self):
        with sqlite3.connect(self.path, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            yield connection

    def record(self, payload: dict, status: str = "completed") -> str:
        serialized = encode(payload)
        experiment_id = hashlib.sha256(serialized.encode()).hexdigest()[:24]
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO experiments VALUES (?, ?, ?, ?)",
                (experiment_id, datetime.now(UTC).isoformat(), status, serialized),
            )
        return experiment_id

    def list(self, limit: int = 20) -> list[dict]:
        if not 1 <= limit <= 1000:
            raise ValueError("查询条数须在 1 到 1000 之间")
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM experiments ORDER BY created_at DESC, id LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) | {"payload": json.loads(row["payload"])} for row in rows]

    def get(self, experiment_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM experiments WHERE id = ?", (experiment_id,)
            ).fetchone()
        if row is None:
            raise ValueError("实验不存在")
        return json.loads(row["payload"])
