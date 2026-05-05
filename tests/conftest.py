"""Gedeelde pytest-fixtures voor de Network as Code-tests."""
from __future__ import annotations
import re
import sqlite3
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SQL = REPO_ROOT / "db" / "schema.sql"
SEED_SQL = REPO_ROOT / "db" / "seed.sql"


def _strip_sql_comments(sql: str) -> str:
    """sqlite3.executescript heeft moeite met inline -- comments."""
    return re.sub(r"--[^\n]*", "", sql)


@pytest.fixture
def tmp_inventory_db(tmp_path: Path) -> Path:
    """Bouw een verse inventory.db in tmp_path vanuit schema.sql + seed.sql."""
    db_path = tmp_path / "inventory.db"
    con = sqlite3.connect(db_path)
    con.executescript(_strip_sql_comments(SCHEMA_SQL.read_text()))
    con.executescript(_strip_sql_comments(SEED_SQL.read_text()))
    con.commit()
    con.close()
    return db_path


@pytest.fixture
def patched_db_path(tmp_inventory_db: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Patcht src.db.DB_PATH zodat zowel db.py als builder.py de tmp DB gebruiken."""
    import src.db
    monkeypatch.setattr(src.db, "DB_PATH", tmp_inventory_db)
    return tmp_inventory_db
