"""SQLite-helper voor de inventory-DB.

De DB wordt opgebouwd vanuit db/schema.sql en db/seed.sql en is in
.gitignore opgenomen — elke ontwikkelaar bouwt zijn eigen lokale DB
vanuit de versiebeheerde bron.

Twee verantwoordelijkheden:
  1. Connectie + lezen van device-configuratie (gebruikt door builder.py).
  2. Schrijven en lezen van de deployments-audittabel (gebruikt door
     deploy.py voor `run`, `show` en `log`).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Repo-root = parent van src/
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "inventory.db"


# ----------------------------------------------------------------------
# Connection
# ----------------------------------------------------------------------
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


# ----------------------------------------------------------------------
# Configuratie-data lezen (builder.py + deploy.py show)
# ----------------------------------------------------------------------
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


def list_devices(con: sqlite3.Connection) -> list[sqlite3.Row]:
    """Alle devices, alfabetisch op naam — voor `deploy list`."""
    return con.execute(
        "SELECT id, name, mgmt_host, netconf_port, platform, "
        "credential_ref, description "
        "FROM devices ORDER BY name"
    ).fetchall()


def get_device(con: sqlite3.Connection, name: str) -> sqlite3.Row:
    """Eén device-rij op naam, of ValueError als het niet bestaat."""
    row = con.execute(
        "SELECT * FROM devices WHERE name = ?", (name,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Device '{name}' niet gevonden in inventory.db")
    return row


# ----------------------------------------------------------------------
# Deployments — audit-log (deploy.py run/show/log)
# ----------------------------------------------------------------------
def _now_iso() -> str:
    """ISO-8601 met UTC-suffix — matcht het formaat in schema.sql."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def insert_deployment(
    con: sqlite3.Connection,
    device_id: int,
    payload_source: str,
    git_commit: Optional[str] = None,
) -> int:
    """Maakt een 'in flight'-rij aan (status='aborted' als veilige default,
    overschreven door update_deployment). Geeft het rij-id terug."""
    cur = con.execute(
        "INSERT INTO deployments "
        "(device_id, started_at, git_commit, payload_source, status) "
        "VALUES (?, ?, ?, ?, 'aborted')",
        (device_id, _now_iso(), git_commit, payload_source),
    )
    con.commit()
    return cur.lastrowid


def update_deployment(
    con: sqlite3.Connection,
    deployment_id: int,
    status: str,
    netconf_reply: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Vult finished_at + status + reply/error in. Status moet
    'success'|'failure'|'aborted' zijn (CHECK in schema)."""
    con.execute(
        "UPDATE deployments SET finished_at = ?, status = ?, "
        "netconf_reply = ?, error_message = ? WHERE id = ?",
        (_now_iso(), status, netconf_reply, error_message, deployment_id),
    )
    con.commit()


def get_recent_deployments(
    con: sqlite3.Connection,
    device_id: int,
    limit: int = 10,
    status: Optional[str] = None,
) -> list[sqlite3.Row]:
    """Recente deployments voor één device, optioneel gefilterd op status."""
    if status is not None:
        return con.execute(
            "SELECT id, started_at, finished_at, status, git_commit, "
            "payload_source, error_message "
            "FROM deployments WHERE device_id = ? AND status = ? "
            "ORDER BY started_at DESC LIMIT ?",
            (device_id, status, limit),
        ).fetchall()
    return con.execute(
        "SELECT id, started_at, finished_at, status, git_commit, "
        "payload_source, error_message "
        "FROM deployments WHERE device_id = ? "
        "ORDER BY started_at DESC LIMIT ?",
        (device_id, limit),
    ).fetchall()


def get_last_deployment(
    con: sqlite3.Connection, device_id: int
) -> Optional[sqlite3.Row]:
    """Meest recente deployment, of None als er nog geen is."""
    rows = get_recent_deployments(con, device_id, limit=1)
    return rows[0] if rows else None
