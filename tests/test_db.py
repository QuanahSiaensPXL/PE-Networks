"""Tests voor src/db.py."""
from __future__ import annotations
from pathlib import Path
import pytest

from src import db


def test_connect_returns_working_connection(patched_db_path: Path):
    con = db.connect()
    try:
        # Foreign keys moeten aan staan (zie db.connect())
        fk = con.execute("PRAGMA foreign_keys;").fetchone()[0]
        assert fk == 1
        # Row-factory moet sqlite3.Row zijn (column-access via name)
        row = con.execute("SELECT name FROM devices WHERE name='R1'").fetchone()
        assert row["name"] == "R1"
    finally:
        con.close()


def test_connect_raises_when_db_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "does_not_exist.db")
    with pytest.raises(FileNotFoundError):
        db.connect()


def test_fetch_device_data_returns_full_structure(patched_db_path: Path):
    con = db.connect()
    try:
        data = db.fetch_device_data(con, "R1")
    finally:
        con.close()

    # Top-level keys
    assert set(data.keys()) == {"device", "interfaces", "static_routes", "vlans"}

    # Device-info matcht seed.sql
    assert data["device"]["name"] == "R1"
    assert data["device"]["mgmt_host"] == "192.168.253.20"
    assert data["device"]["netconf_port"] == 830
    assert data["device"]["platform"] == "iosxe"
    assert data["device"]["credential_ref"] == "R1_NETCONF"

    # Aantal rijen per tabel
    assert len(data["interfaces"]) == 2
    assert len(data["static_routes"]) == 1
    assert len(data["vlans"]) == 2


def test_fetch_device_data_interfaces_have_expected_fields(patched_db_path: Path):
    con = db.connect()
    try:
        data = db.fetch_device_data(con, "R1")
    finally:
        con.close()

    # Volgorde is ORDER BY name → Gi2 voor Gi3
    names = [i["name"] for i in data["interfaces"]]
    assert names == ["GigabitEthernet2", "GigabitEthernet3"]

    gi2 = data["interfaces"][0]
    assert gi2["ipv4_address"] == "10.10.10.1"
    assert gi2["ipv4_netmask"] == "255.255.255.0"
    assert gi2["enabled"] == 1
    assert "VLAN 10" in gi2["description"]


def test_fetch_device_data_vlans_have_expected_fields(patched_db_path: Path):
    con = db.connect()
    try:
        data = db.fetch_device_data(con, "R1")
    finally:
        con.close()

    by_id = {v["vlan_id"]: v["vlan_name"] for v in data["vlans"]}
    assert by_id == {10: "DATA", 20: "VOICE"}


def test_fetch_device_data_raises_for_unknown_device(patched_db_path: Path):
    con = db.connect()
    try:
        with pytest.raises(ValueError, match="UNKNOWN"):
            db.fetch_device_data(con, "UNKNOWN")
    finally:
        con.close()
