"""Standalone integration check: stuur R1-baseline.xml als NETCONF dry-run.

Dit is GEEN unit test — het vereist netwerktoegang tot een echte CSR1000v
of ISR4221. Het wordt apart uitgevoerd, niet via pytest:

    python -m tests.check_baseline_netconf

Default-target: Andries' lokale CSR1000v (192.168.253.131). Override met
env vars: NETCONF_HOST, NETCONF_PORT, NETCONF_USER, NETCONF_PASS.

Wat het doet:
  1. Opent NETCONF-sessie en print server-capabilities.
  2. Leest configs/generated/R1-baseline.xml.
  3. Voert een DRY-RUN uit: lock(candidate) → edit-config(candidate) →
     validate(candidate) → DISCARD-CHANGES → unlock(candidate).
  4. Geen <commit/> wordt aangeroepen — niets wordt permanent toegepast.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

from ncclient import manager
from ncclient.operations import RPCError

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE = REPO_ROOT / "configs" / "generated" / "R1-baseline.xml"

HOST = os.environ.get("NETCONF_HOST", "192.168.253.131")
PORT = int(os.environ.get("NETCONF_PORT", "830"))
USER = os.environ.get("NETCONF_USER", "cisco")
PASS = os.environ.get("NETCONF_PASS", "cisco123!")


def _wrap_in_config(payload_xml: str) -> str:
    """Verwijder XML-declaration en wrap in NETCONF <config>."""
    if payload_xml.startswith("<?xml"):
        payload_xml = payload_xml.split("?>", 1)[1].lstrip()
    return f'<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">{payload_xml}</config>'


def main() -> int:
    if not BASELINE.exists():
        print(f"[FAIL] Baseline ontbreekt op {BASELINE}.")
        print("       Bouw eerst met: python -m src build R1")
        return 1

    payload = BASELINE.read_text(encoding="utf-8")
    config_block = _wrap_in_config(payload)

    print(f"[INFO] Verbinden met {USER}@{HOST}:{PORT} ...")
    try:
        with manager.connect(
            host=HOST,
            port=PORT,
            username=USER,
            password=PASS,
            hostkey_verify=False,
            timeout=30,
            device_params={"name": "iosxe"},
        ) as m:
            caps = list(m.server_capabilities)
            has_candidate = any(":candidate" in c for c in caps)
            has_validate = any(":validate" in c for c in caps)
            has_rollback = any(":rollback-on-error" in c for c in caps)

            print(f"[INFO] Sessie open (session-id={m.session_id}).")
            print( "[INFO] Capabilities:")
            print(f"         :candidate         {'JA' if has_candidate else 'NEE'}")
            print(f"         :validate          {'JA' if has_validate else 'NEE'}")
            print(f"         :rollback-on-error {'JA' if has_rollback else 'NEE'}")

            if not has_candidate:
                print("[FAIL] Geen :candidate-datastore. Schakel deze in op de router")
                print("       met: 'netconf-yang feature candidate-datastore'.")
                return 2

            print("[STEP] lock(candidate) ...")
            m.lock(target="candidate")
            try:
                print("[STEP] edit-config(candidate) — payload pushen ...")
                edit_reply = m.edit_config(target="candidate", config=config_block)
                if edit_reply.ok:
                    print("[ OK ] edit-config geaccepteerd door server.")
                else:
                    print("[FAIL] edit-config afgewezen:")
                    print(edit_reply.xml)
                    return 3

                if has_validate:
                    print("[STEP] validate(candidate) ...")
                    val_reply = m.validate(source="candidate")
                    if val_reply.ok:
                        print("[ OK ] validate succesvol — payload is YANG-conform.")
                    else:
                        print("[FAIL] validate-fouten:")
                        print(val_reply.xml)
                        return 4

                print("[STEP] discard-changes — niets wordt permanent toegepast.")
                m.discard_changes()
            finally:
                print("[STEP] unlock(candidate) ...")
                m.unlock(target="candidate")

        print()
        print("[DONE] Dry-run geslaagd. Baseline-XML is geldig op deze router.")
        return 0

    except RPCError as e:
        print(f"[FAIL] NETCONF-fout: {e}")
        return 5
    except Exception as e:
        print(f"[FAIL] Onverwachte fout: {type(e).__name__}: {e}")
        return 6


if __name__ == "__main__":
    sys.exit(main())
