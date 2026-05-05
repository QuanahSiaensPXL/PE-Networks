"""SQLite-helper voor de inventory-DB.

De DB wordt opgebouwd vanuit db/schema.sql en db/seed.sql en is in
.gitignore opgenomen — elke ontwikkelaar bouwt zijn eigen lokale DB
vanuit de versiebeheerde bron.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

# Repo-root = parent van src/
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "inventory.db"


def connect() -> sqlite3.Connection:
    """Open inventory.db met Row-factory en foreign keys aan."""
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"inventory.db niet gevonden op {DB_PATH}.\n"
            "Bouw eerst de DB met:\n"
            "  sqlite3 inventory.db < db/schema.sql\n"
            "  sqlite3 inventory.db < db/seed.sql"
        )
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON;")
    return con


def fetch_device_data(con: sqlite3.Connection, device_name: str) -> dict:
    """Lees alle relevante rijen voor device en returneer als dicts.

    Returns:
        {
            "device": {...},
            "interfaces": [{...}, ...],
            "static_routes": [{...}, ...],
            "vlans": [{...}, ...],
        }
    """
    device = con.execute(
        "SELECT * FROM devices WHERE name = ?", (device_name,)
    ).fetchone()
    if device is None:
        raise ValueError(f"Device '{device_name}' niet gevonden in inventory.db")

    device_id = device["id"]
    return {
        "device": dict(device),
        "interfaces": [
            dict(r) for r in con.execute(
                "SELECT * FROM interfaces WHERE device_id = ? ORDER BY name",
                (device_id,),
            )
        ],
        "static_routes": [
            dict(r) for r in con.execute(
                "SELECT * FROM static_routes WHERE device_id = ? ORDER BY id",
                (device_id,),
            )
        ],
        "vlans": [
            dict(r) for r in con.execute(
                "SELECT * FROM vlans WHERE device_id = ? ORDER BY vlan_id",
                (device_id,),
            )
        ],
    }
