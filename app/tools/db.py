"""SQLite access to the prepared extracts (build/tcc.db). Read-only."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app import config

_local = threading.local()
_override: Path | None = None


def use_database(path: str | Path | None) -> None:
    """Point tools at another DB (tests). None restores the default."""
    global _override
    _override = Path(path) if path else None
    _local.__dict__.clear()


def conn() -> sqlite3.Connection:
    path = _override or config.DB_PATH
    c = getattr(_local, "conn", None)
    if c is None or getattr(_local, "path", None) != path:
        if not Path(path).exists():
            raise FileNotFoundError(f"{path} missing - run: python scripts/prepare_data.py")
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        c.row_factory = sqlite3.Row
        _local.conn, _local.path = c, path
    return c


def query(sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, params).fetchall()]
