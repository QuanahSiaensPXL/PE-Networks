"""Network as Code — CLI.

Subcommands:
  build   render templates + fragments tot configs/generated/<device>-baseline.xml
  list    toon devices uit inventory.db                                  [Quanah]
  show    device-detail + laatste deploy-status                          [Quanah]
  run     haal baseline van GitHub, voer NETCONF-deploy uit              [Quanah]
  log     chronologisch overzicht van deploys                            [Quanah]

Aanroep:
    python -m src list
    python -m src show R1
    python -m src run  R1 --dry-run
    python -m src log  R1 --limit 5 --status success

Credentials komen uit .env: <credential_ref>_USERNAME en
<credential_ref>_PASSWORD (bv. R1_NETCONF_USERNAME / _PASSWORD).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

import click
from dotenv import load_dotenv

from . import builder
from . import db

# ncclient mag ontbreken voor list/show/log — alleen `run` heeft het echt
# nodig. Lazy import zodat unit-tests zonder NETCONF-stack kunnen draaien.
try:
    from ncclient import manager  # noqa: F401
    NCCLIENT_AVAILABLE = True
except ImportError:  # pragma: no cover
    NCCLIENT_AVAILABLE = False


ROOT = Path(__file__).resolve().parent.parent
PAYLOAD_DIR = ROOT / "configs" / "generated"
NS_NETCONF = "urn:ietf:params:xml:ns:netconf:base:1.0"


# ======================================================================
# Helpers — privé, herbruikt door meerdere subcommands.
# ======================================================================
def _load_env() -> None:
    """Leest .env in indien aanwezig; geen error als het ontbreekt."""
    env_path = ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def _git_commit() -> Optional[str]:
    """Korte HEAD-hash, of None buiten een git-checkout."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _credentials(credential_ref: str) -> tuple[str, str]:
    """Haalt <ref>_USERNAME en <ref>_PASSWORD uit de environment."""
    user = os.environ.get(f"{credential_ref}_USERNAME")
    pwd = os.environ.get(f"{credential_ref}_PASSWORD")
    if not user or not pwd:
        raise click.ClickException(
            f"Credentials niet gevonden in .env voor {credential_ref}.\n"
            f"Verwacht: {credential_ref}_USERNAME en {credential_ref}_PASSWORD."
        )
    return user, pwd


def _format_status(status: Optional[str]) -> str:
    """Korte iconen voor in tabellen — hetzelfde formaat in list/show/log."""
    return {
        "success": "✓ success",
        "failure": "✗ failure",
        "aborted": "… aborted",
        None: "— (geen)",
    }.get(status, status or "—")


def _read_payload(device_name: str) -> str:
    """Leest configs/generated/<device>-baseline.xml. Faalt netjes als
    de gebruiker `build` vergeten is."""
    path = PAYLOAD_DIR / f"{device_name}-baseline.xml"
    if not path.exists():
        raise click.ClickException(
            f"Payload {path.name} niet gevonden in {PAYLOAD_DIR}.\n"
            f"Bouw die eerst met:  python -m src build {device_name}"
        )
    return path.read_text(encoding="utf-8")


def _wrap_in_config(payload: str) -> str:
    """Wrap een <native>-payload in een NETCONF <config>-envelope.

    builder.build() levert een kale <native>-tree (zonder envelope) zodat
    de bouw-stap los kan blijven van de NETCONF-laag. edit-config heeft
    wél een <config>-element nodig, dus we voegen het hier toe.
    """
    # Strip XML-declaratie als die er is — die mag niet binnen <config>.
    body = payload
    if body.lstrip().startswith("<?xml"):
        body = body.split("?>", 1)[1].lstrip()
    return f'<config xmlns="{NS_NETCONF}">{body}</config>'


# ======================================================================
# NETCONF-laag — capability-aware deploy.
# ======================================================================
def _has_capability(caps, needle: str) -> bool:
    return any(needle in str(c) for c in caps)


def _open_session(device, timeout: int = 30):
    """Opent een ncclient-sessie met de credentials uit .env."""
    if not NCCLIENT_AVAILABLE:
        raise click.ClickException(
            "ncclient is niet geïnstalleerd. Run: pip install ncclient"
        )
    user, pwd = _credentials(device["credential_ref"])
    return manager.connect(
        host=device["mgmt_host"],
        port=device["netconf_port"],
        username=user,
        password=pwd,
        hostkey_verify=False,
        device_params={"name": "iosxe"},
        timeout=timeout,
        look_for_keys=False,
        allow_agent=False,
    )


def _summarise_reply(reply) -> str:
    """Houdt de NETCONF-reply samenvatting kort genoeg voor de DB-kolom."""
    if reply is None:
        return ""
    xml = getattr(reply, "xml", str(reply))
    return xml[:500]  # voldoende voor <ok/> of korte <rpc-error>


def deploy_payload(m, payload_xml: str, dry_run: bool = False) -> tuple[str, str]:
    """Voert de eigenlijke NETCONF-deploy uit op een open sessie.

    Capability-aware:
      * :candidate aanwezig → lock candidate, edit-config target=candidate,
                              :validate (indien aanwezig), commit, unlock.
      * geen :candidate     → lock running, edit-config target=running, unlock.
                              (--dry-run wordt geweigerd: niet veilig zonder
                              candidate-datastore.)

    Lock-discipline: target wordt altijd ge-unlocked, ook bij fouten.
    """
    caps = list(m.server_capabilities)
    has_candidate = _has_capability(caps, "candidate:1.0")
    has_validate = _has_capability(caps, "validate")
    has_rollback = _has_capability(caps, "rollback-on-error")
    target = "candidate" if has_candidate else "running"

    config_xml = _wrap_in_config(payload_xml)

    m.lock(target=target)
    try:
        # Candidate kan vorige (gefaalde) sessie-state bevatten — opschonen.
        if has_candidate:
            m.discard_changes()

        edit_kwargs: dict = {"target": target, "config": config_xml}
        if has_rollback:
            edit_kwargs["error_option"] = "rollback-on-error"
        edit_reply = m.edit_config(**edit_kwargs)

        # :validate werkt alleen betrouwbaar op candidate in IOS-XE.
        if has_validate and target == "candidate":
            m.validate(source="candidate")

        if target == "candidate":
            if dry_run:
                m.discard_changes()
                return "dry-run", _summarise_reply(edit_reply)
            commit_reply = m.commit()
            return "success", _summarise_reply(commit_reply)

        # target=running — edit-config zelf ís de commit.
        if dry_run:
            raise click.ClickException(
                "--dry-run vereist :candidate-capability op het toestel "
                "(niet aanwezig hier). Test eerst tegen CSR1000v."
            )
        return "success", _summarise_reply(edit_reply)
    finally:
        m.unlock(target=target)


# ======================================================================
# CLI — Click groep + subcommando's, naam-conventie cmd_<name>.
# ======================================================================
@click.group(help="Network as Code — IOS-XE baseline-deployment via NETCONF.")
def cli():
    _load_env()


@cli.command(name="build")
@click.argument("device")
def cmd_build(device):
    """Render baseline-XML voor DEVICE (bv. R1)."""
    path = builder.build(device)
    click.echo(f"Baseline geschreven naar {path.relative_to(builder.ROOT)}")


# ----------------------------------------------------------------------
# list — devices + laatste deploy-status
# ----------------------------------------------------------------------
@cli.command(name="list")
def cmd_list():
    """Toon alle devices uit inventory.db."""
    con = db.connect()
    try:
        devices = db.list_devices(con)
        if not devices:
            click.echo("Geen devices in inventory.db.")
            return
        click.echo(
            f"{'NAME':<8} {'HOST':<18} {'PORT':<6} {'PLATFORM':<10} "
            f"{'LAST DEPLOY':<22} STATUS"
        )
        click.echo("-" * 80)
        for d in devices:
            last = db.get_last_deployment(con, d["id"])
            last_when = last["started_at"] if last else "—"
            last_status = _format_status(last["status"] if last else None)
            click.echo(
                f"{d['name']:<8} {d['mgmt_host']:<18} {d['netconf_port']:<6} "
                f"{d['platform']:<10} {last_when:<22} {last_status}"
            )
    finally:
        con.close()


# ----------------------------------------------------------------------
# show — detail van één device
# ----------------------------------------------------------------------
@cli.command(name="show")
@click.argument("device")
def cmd_show(device):
    """Toon device-detail + laatste deploy-status."""
    con = db.connect()
    try:
        try:
            data = db.fetch_device_data(con, device)
        except ValueError as e:
            raise click.ClickException(str(e))
        d = data["device"]

        click.echo(f"Device: {d['name']}")
        click.echo(f"  Host        : {d['mgmt_host']}:{d['netconf_port']}")
        click.echo(f"  Platform    : {d['platform']}")
        click.echo(f"  Credentials : {d['credential_ref']}_(USERNAME|PASSWORD) in .env")
        if d.get("description"):
            click.echo(f"  Description : {d['description']}")

        click.echo(f"\nInterfaces ({len(data['interfaces'])}):")
        for i in data["interfaces"]:
            up = "up" if i["enabled"] else "shutdown"
            click.echo(
                f"  {i['name']:<20} {i['ipv4_address']}/{i['ipv4_netmask']}  "
                f"[{up}]  {i.get('description') or ''}"
            )

        click.echo(f"\nStatic routes ({len(data['static_routes'])}):")
        for r in data["static_routes"]:
            click.echo(
                f"  {r['dest_prefix']}/{r['dest_netmask']} via {r['next_hop']}"
                f"   {r.get('description') or ''}"
            )

        click.echo(f"\nVLANs ({len(data['vlans'])}):")
        for v in data["vlans"]:
            click.echo(f"  {v['vlan_id']:<5} {v['vlan_name']}")

        recent = db.get_recent_deployments(con, d["id"], limit=3)
        click.echo(f"\nLaatste deployments ({len(recent)}):")
        if not recent:
            click.echo("  (nog geen deploys uitgevoerd)")
        for dep in recent:
            click.echo(
                f"  #{dep['id']}  {dep['started_at']}  "
                f"{_format_status(dep['status'])}  "
                f"commit={dep['git_commit'] or '—'}"
            )
    finally:
        con.close()


# ----------------------------------------------------------------------
# run — NETCONF-deploy
# ----------------------------------------------------------------------
@cli.command(name="run")
@click.argument("device")
@click.option("--dry-run", is_flag=True,
              help="Voer edit-config + validate uit, daarna discard "
                   "(vereist :candidate-capability).")
@click.option("--timeout", default=30, show_default=True,
              help="NETCONF-timeout in seconden.")
def cmd_run(device, dry_run, timeout):
    """Voer NETCONF-deploy uit op DEVICE.

    Stappen: read payload → connect → capability-detect → lock → edit-config
    → validate (indien beschikbaar) → commit (of discard bij --dry-run)
    → unlock. Schrijft een rij in de deployments-tabel, ook bij failure.
    """
    con = db.connect()
    try:
        try:
            d = db.get_device(con, device)
        except ValueError as e:
            raise click.ClickException(str(e))

        payload = _read_payload(device)
        commit = _git_commit()
        payload_source = f"configs/generated/{device}-baseline.xml"
        if commit:
            payload_source += f"@{commit}"

        deployment_id = db.insert_deployment(
            con, d["id"], payload_source=payload_source, git_commit=commit
        )
        click.echo(
            f"→ Deploy #{deployment_id} voor {device} "
            f"({d['mgmt_host']}:{d['netconf_port']})"
            + (" [DRY-RUN]" if dry_run else "")
        )

        try:
            with _open_session(d, timeout=timeout) as m:
                caps = list(m.server_capabilities)
                click.echo(
                    "  Capabilities: "
                    f"candidate={_has_capability(caps, 'candidate:1.0')}, "
                    f"validate={_has_capability(caps, 'validate')}, "
                    f"rollback={_has_capability(caps, 'rollback-on-error')}"
                )
                status, reply_summary = deploy_payload(m, payload, dry_run=dry_run)
        except click.ClickException:
            db.update_deployment(
                con, deployment_id, status="aborted",
                error_message="afgebroken door precondition (zie output)",
            )
            raise
        except Exception as exc:  # noqa: BLE001 — we willen écht alles vangen
            db.update_deployment(
                con, deployment_id, status="failure",
                error_message=f"{type(exc).__name__}: {exc}",
            )
            raise click.ClickException(f"Deploy gefaald: {exc}")

        # status='success' (committed) of 'dry-run' (gevalideerd, niet committed)
        # — beide opslaan als 'success' in de DB; CHECK-constraint laat geen
        # vrije strings toe. We onderscheiden via netconf_reply / payload_source.
        db_status = "success"
        db.update_deployment(
            con, deployment_id, status=db_status,
            netconf_reply=reply_summary,
        )
        click.echo(f"  ✓ {status} (deployment #{deployment_id})")
    finally:
        con.close()


# ----------------------------------------------------------------------
# log — chronologisch overzicht
# ----------------------------------------------------------------------
@cli.command(name="log")
@click.argument("device")
@click.option("--limit", default=10, show_default=True,
              help="Maximum aantal rijen.")
@click.option("--status",
              type=click.Choice(["success", "failure", "aborted"]),
              default=None, help="Alleen rijen met deze status tonen.")
def cmd_log(device, limit, status):
    """Toon deploy-historie voor DEVICE."""
    con = db.connect()
    try:
        try:
            d = db.get_device(con, device)
        except ValueError as e:
            raise click.ClickException(str(e))
        rows = db.get_recent_deployments(con, d["id"], limit=limit, status=status)
        if not rows:
            click.echo(f"Geen deployments gevonden voor {device}.")
            return
        click.echo(
            f"{'ID':<5} {'STARTED':<22} {'FINISHED':<22} {'STATUS':<11} "
            f"{'COMMIT':<10} PAYLOAD"
        )
        click.echo("-" * 100)
        for r in rows:
            click.echo(
                f"{r['id']:<5} {r['started_at']:<22} "
                f"{(r['finished_at'] or '—'):<22} "
                f"{_format_status(r['status']):<11} "
                f"{(r['git_commit'] or '—'):<10} "
                f"{r['payload_source']}"
            )
            if r["error_message"]:
                click.echo(f"      ↳ error: {r['error_message']}")
    finally:
        con.close()


if __name__ == "__main__":
    cli()
