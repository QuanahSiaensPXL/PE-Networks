"""
Tests voor src/deploy.py.

Drie lagen:
  1. Pure unit-tests op helpers (_wrap_in_config, _format_status,
     _credentials, _has_capability) — geen IO, geen DB.
  2. CLI-tests met click.testing.CliRunner op list/show/log — gebruiken
     de patched_db_path-fixture uit conftest.py voor een echte tmp-DB.
  3. NETCONF-tests op cmd_run met een FakeManager — capability-detectie,
     lock/unlock-discipline, dry-run, error-handling.

Aanroep: pytest -v tests/test_deploy.py
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import click
import pytest
from click.testing import CliRunner

from src import db, deploy

NS_NETCONF = "urn:ietf:params:xml:ns:netconf:base:1.0"


# ======================================================================
# 1. UNIT-TESTS — pure helpers
# ======================================================================
class TestWrapInConfig:
    def test_adds_netconf_namespace(self):
        out = deploy._wrap_in_config('<native xmlns="x"><hostname>R1</hostname></native>')
        assert NS_NETCONF in out
        assert out.startswith(f'<config xmlns="{NS_NETCONF}">')
        assert out.endswith("</config>")

    def test_strips_xml_declaration(self):
        payload = '<?xml version="1.0" encoding="UTF-8"?>\n<native xmlns="x"/>'
        out = deploy._wrap_in_config(payload)
        assert "<?xml" not in out  # niet binnen <config>

    def test_preserves_native_body(self):
        body = '<native xmlns="x"><hostname>R1</hostname></native>'
        out = deploy._wrap_in_config(body)
        assert "<hostname>R1</hostname>" in out


class TestFormatStatus:
    @pytest.mark.parametrize("status,expected_prefix", [
        ("success", "✓"),
        ("failure", "✗"),
        ("aborted", "…"),
    ])
    def test_known_statuses_get_icon(self, status, expected_prefix):
        assert deploy._format_status(status).startswith(expected_prefix)

    def test_none_returns_dash(self):
        assert "—" in deploy._format_status(None)


class TestCredentials:
    def test_missing_username_raises(self, monkeypatch):
        monkeypatch.delenv("R1_NETCONF_USERNAME", raising=False)
        monkeypatch.delenv("R1_NETCONF_PASSWORD", raising=False)
        with pytest.raises(click.ClickException, match="R1_NETCONF"):
            deploy._credentials("R1_NETCONF")

    def test_present_returns_tuple(self, monkeypatch):
        monkeypatch.setenv("R1_NETCONF_USERNAME", "admin")
        monkeypatch.setenv("R1_NETCONF_PASSWORD", "secret")
        assert deploy._credentials("R1_NETCONF") == ("admin", "secret")


class TestHasCapability:
    def test_finds_substring(self):
        caps = [
            "urn:ietf:params:netconf:base:1.0",
            "urn:ietf:params:netconf:capability:candidate:1.0",
        ]
        assert deploy._has_capability(caps, "candidate:1.0")
        assert not deploy._has_capability(caps, "writable-running")


# ======================================================================
# 2. CLI-TESTS — list / show / log via CliRunner + patched_db_path
# ======================================================================
@pytest.fixture
def runner():
    return CliRunner()


class TestCmdList:
    def test_lists_seeded_device(self, runner, patched_db_path: Path):
        result = runner.invoke(deploy.cli, ["list"])
        assert result.exit_code == 0, result.output
        assert "R1" in result.output
        assert "192.168.253" in result.output  # mgmt_host kolom

    def test_shows_no_deploy_yet(self, runner, patched_db_path: Path):
        """Verse DB → laatste deploy-kolom toont een dash."""
        result = runner.invoke(deploy.cli, ["list"])
        assert result.exit_code == 0
        assert "geen" in result.output.lower() or "—" in result.output


class TestCmdShow:
    def test_shows_device_details(self, runner, patched_db_path: Path):
        result = runner.invoke(deploy.cli, ["show", "R1"])
        assert result.exit_code == 0, result.output
        assert "R1" in result.output
        assert "GigabitEthernet2" in result.output
        assert "GigabitEthernet3" in result.output
        assert "DATA" in result.output  # VLAN-naam
        assert "VOICE" in result.output

    def test_unknown_device_returns_error(self, runner, patched_db_path: Path):
        result = runner.invoke(deploy.cli, ["show", "NONEXISTENT"])
        assert result.exit_code != 0
        assert "NONEXISTENT" in result.output


class TestCmdLog:
    def test_empty_log_when_no_deployments(self, runner, patched_db_path: Path):
        result = runner.invoke(deploy.cli, ["log", "R1"])
        assert result.exit_code == 0
        assert "Geen" in result.output or "geen" in result.output

    def test_log_shows_inserted_deployment(self, runner, patched_db_path: Path):
        # Voeg handmatig een deployment-rij toe
        con = db.connect()
        try:
            d = db.get_device(con, "R1")
            db.insert_deployment(con, d["id"], "configs/generated/R1-baseline.xml",
                                 git_commit="abc1234")
        finally:
            con.close()
        result = runner.invoke(deploy.cli, ["log", "R1"])
        assert result.exit_code == 0
        assert "abc1234" in result.output

    def test_log_filters_by_status(self, runner, patched_db_path: Path):
        # 1 success, 1 failure
        con = db.connect()
        try:
            d = db.get_device(con, "R1")
            ok_id = db.insert_deployment(con, d["id"], "p1", git_commit="aaa")
            db.update_deployment(con, ok_id, status="success")
            fail_id = db.insert_deployment(con, d["id"], "p2", git_commit="bbb")
            db.update_deployment(con, fail_id, status="failure",
                                 error_message="boom")
        finally:
            con.close()

        result = runner.invoke(deploy.cli, ["log", "R1", "--status", "success"])
        assert result.exit_code == 0
        assert "aaa" in result.output
        assert "bbb" not in result.output


# ======================================================================
# 3. NETCONF-TESTS — cmd_run met een FakeManager
# ======================================================================
class FakeRPCReply:
    """Mimics ncclient.RPCReply genoeg voor _summarise_reply."""
    def __init__(self, xml: str = "<ok/>"):
        self.xml = xml


class FakeManager:
    """Mimics een ncclient.Manager voor unit-tests.

    Logt elke call in self.calls als (method, *args). Default
    capabilities = volledige IOS-XE 16.x set; via constructor te overrulen
    om bv. een toestel zónder :candidate te simuleren (ISR4221).
    """
    def __init__(self, capabilities=None, edit_config_raises=None):
        self.server_capabilities = capabilities or [
            "urn:ietf:params:netconf:base:1.0",
            "urn:ietf:params:netconf:capability:candidate:1.0",
            "urn:ietf:params:netconf:capability:validate:1.0",
            "urn:ietf:params:netconf:capability:rollback-on-error:1.0",
            "urn:ietf:params:netconf:capability:writable-running:1.0",
        ]
        self.calls: list[tuple] = []
        self._edit_config_raises = edit_config_raises

    # context-manager protocol — `with _open_session(...) as m:` werkt
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False  # exceptions doorlaten

    def lock(self, target):
        self.calls.append(("lock", target))

    def unlock(self, target):
        self.calls.append(("unlock", target))

    def discard_changes(self):
        self.calls.append(("discard_changes",))

    def edit_config(self, target, config, error_option=None):
        self.calls.append(("edit_config", target, error_option))
        if self._edit_config_raises:
            raise self._edit_config_raises
        return FakeRPCReply()

    def validate(self, source):
        self.calls.append(("validate", source))
        return FakeRPCReply()

    def commit(self):
        self.calls.append(("commit",))
        return FakeRPCReply()


@pytest.fixture
def fake_payload(tmp_path, monkeypatch):
    """Schrijf een minimale baseline-XML en patch PAYLOAD_DIR ernaartoe."""
    payload_dir = tmp_path / "generated"
    payload_dir.mkdir()
    payload = (payload_dir / "R1-baseline.xml")
    payload.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<native xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-native">'
        '<hostname>R1</hostname>'
        '</native>',
        encoding="utf-8",
    )
    monkeypatch.setattr(deploy, "PAYLOAD_DIR", payload_dir)
    return payload


@pytest.fixture
def env_credentials(monkeypatch):
    """Zet R1_NETCONF_USERNAME / _PASSWORD zodat _credentials niet faalt."""
    monkeypatch.setenv("R1_NETCONF_USERNAME", "admin")
    monkeypatch.setenv("R1_NETCONF_PASSWORD", "secret")


def _patch_open_session(monkeypatch, fake: FakeManager):
    """Vervangt deploy._open_session zodat 'with _open_session(...) as m'
    onze FakeManager teruggeeft."""
    monkeypatch.setattr(deploy, "_open_session",
                        lambda device, timeout=30: fake)


class TestCmdRunHappyPath:
    def test_with_candidate_does_lock_edit_validate_commit_unlock(
        self, runner, patched_db_path, fake_payload, env_credentials, monkeypatch
    ):
        fake = FakeManager()  # default = volledige caps
        _patch_open_session(monkeypatch, fake)

        result = runner.invoke(deploy.cli, ["run", "R1"])
        assert result.exit_code == 0, result.output

        methods = [c[0] for c in fake.calls]
        # Verwachte volgorde
        assert methods == [
            "lock", "discard_changes", "edit_config",
            "validate", "commit", "unlock",
        ]
        # Lock op candidate, niet op running
        assert ("lock", "candidate") in fake.calls
        assert ("unlock", "candidate") in fake.calls

    def test_records_success_in_deployments_table(
        self, runner, patched_db_path, fake_payload, env_credentials, monkeypatch
    ):
        _patch_open_session(monkeypatch, FakeManager())
        runner.invoke(deploy.cli, ["run", "R1"])

        con = db.connect()
        try:
            row = con.execute(
                "SELECT status, finished_at, netconf_reply FROM deployments "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            con.close()
        assert row["status"] == "success"
        assert row["finished_at"] is not None
        assert "ok" in row["netconf_reply"].lower()


class TestCmdRunDryRun:
    def test_dry_run_discards_and_does_not_commit(
        self, runner, patched_db_path, fake_payload, env_credentials, monkeypatch
    ):
        fake = FakeManager()
        _patch_open_session(monkeypatch, fake)

        result = runner.invoke(deploy.cli, ["run", "R1", "--dry-run"])
        assert result.exit_code == 0, result.output

        methods = [c[0] for c in fake.calls]
        assert "commit" not in methods
        # discard_changes komt 2x voor: één keer initieel (cleanup),
        # één keer aan het eind voor de dry-run rollback.
        assert methods.count("discard_changes") == 2
        assert "unlock" in methods  # finally-clause moet altijd unlocken


class TestCmdRunWithoutCandidate:
    def test_without_candidate_locks_running_and_no_validate(
        self, runner, patched_db_path, fake_payload, env_credentials, monkeypatch
    ):
        # Simuleer een ISR4221-achtig toestel: alleen writable-running.
        caps = [
            "urn:ietf:params:netconf:base:1.0",
            "urn:ietf:params:netconf:capability:writable-running:1.0",
        ]
        fake = FakeManager(capabilities=caps)
        _patch_open_session(monkeypatch, fake)

        result = runner.invoke(deploy.cli, ["run", "R1"])
        assert result.exit_code == 0, result.output

        methods = [c[0] for c in fake.calls]
        assert "validate" not in methods
        assert "commit" not in methods
        assert ("lock", "running") in fake.calls
        assert ("unlock", "running") in fake.calls

    def test_dry_run_without_candidate_aborts(
        self, runner, patched_db_path, fake_payload, env_credentials, monkeypatch
    ):
        caps = [
            "urn:ietf:params:netconf:base:1.0",
            "urn:ietf:params:netconf:capability:writable-running:1.0",
        ]
        fake = FakeManager(capabilities=caps)
        _patch_open_session(monkeypatch, fake)

        result = runner.invoke(deploy.cli, ["run", "R1", "--dry-run"])
        assert result.exit_code != 0
        assert "candidate" in result.output

        # DB moet 'aborted' geregistreerd hebben
        con = db.connect()
        try:
            row = con.execute(
                "SELECT status FROM deployments ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            con.close()
        assert row["status"] == "aborted"


class TestCmdRunFailureModes:
    def test_edit_config_failure_records_failure_and_unlocks(
        self, runner, patched_db_path, fake_payload, env_credentials, monkeypatch
    ):
        fake = FakeManager(edit_config_raises=RuntimeError("rpc-error: bad-element"))
        _patch_open_session(monkeypatch, fake)

        result = runner.invoke(deploy.cli, ["run", "R1"])
        assert result.exit_code != 0

        # Lock moet vrijgegeven zijn ook na de exception
        methods = [c[0] for c in fake.calls]
        assert methods.count("lock") == methods.count("unlock") == 1

        # DB-rij moet status='failure' hebben
        con = db.connect()
        try:
            row = con.execute(
                "SELECT status, error_message FROM deployments "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            con.close()
        assert row["status"] == "failure"
        assert "rpc-error" in (row["error_message"] or "")

    def test_missing_payload_errors_clearly(
        self, runner, patched_db_path, env_credentials, monkeypatch, tmp_path
    ):
        # Geen baseline-XML → helder error-bericht, geen NETCONF-call
        monkeypatch.setattr(deploy, "PAYLOAD_DIR", tmp_path / "leeg")
        result = runner.invoke(deploy.cli, ["run", "R1"])
        assert result.exit_code != 0
        assert "build" in result.output  # hint naar `python -m src build`

    def test_unknown_device_errors_before_netconf(
        self, runner, patched_db_path, fake_payload, env_credentials
    ):
        result = runner.invoke(deploy.cli, ["run", "GHOST"])
        assert result.exit_code != 0
        assert "GHOST" in result.output
