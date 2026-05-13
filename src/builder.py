"""Builder: combineer DB-data, Jinja-templates en statische YANG-fragments
tot één coherente baseline-XML payload voor IOS-XE.

Strategie:
  1. Statische fragments uit fragments/ (nummervolgorde) — voor de 6 taken
     die een vaste configuratie hebben (hostname, banner, loopback, NTP, DNS,
     OSPF).
  2. DB-driven templates uit templates/ — voor de 3 taken die per device
     verschillen (interfaces, static_routes, vlans).
  3. Smart merge tot één <native>-tree: top-level containers die in meerdere
     subtrees voorkomen (bv. <interface>, <ip>) worden samengevoegd, zodat de
     uiteindelijke XML schema-conform is.

Output: configs/generated/<device>-baseline.xml — pretty-printed, zonder
NETCONF <config>-envelope (die voegt deploy.py toe op het moment van de
deploy).
"""
from __future__ import annotations
from pathlib import Path
from lxml import etree
from jinja2 import Environment, FileSystemLoader

from . import db

NATIVE_NS = "http://cisco.com/ns/yang/Cisco-IOS-XE-native"

ROOT = Path(__file__).resolve().parent.parent
FRAGMENTS_DIR = ROOT / "fragments"
TEMPLATES_DIR = ROOT / "templates"
OUTPUT_DIR = ROOT / "configs" / "generated"


def _load_fragments() -> list:
    """Lees alle XML-fragments in nummervolgorde (01_, 02_, ..., 10_)."""
    files = sorted(p for p in FRAGMENTS_DIR.iterdir() if p.suffix == ".xml")
    return [etree.parse(str(p)).getroot() for p in files]


def _render_templates(data: dict) -> list:
    """Render de 3 Jinja-templates met device-data. Lege lists worden
    overgeslagen om geen lege containers in de output te krijgen.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    pairs = [
        ("interfaces.xml.j2", "interfaces"),
        ("static_routes.xml.j2", "static_routes"),
        ("vlans.xml.j2", "vlans"),
    ]
    rendered = []
    for tname, key in pairs:
        if not data[key]:
            continue
        xml_str = env.get_template(tname).render(**{key: data[key]})
        rendered.append(etree.fromstring(xml_str.encode()))
    return rendered


def _merge_native_subtrees(subtrees: list):
    """Combineer meerdere <native>-subtrees in één.

    Top-level tags die in meerdere subtrees voorkomen worden samengevoegd:
    de eerste subtree-kind wordt het anker, daarna worden de children van
    elke duplicate child eraan toegevoegd. Voor text-only elementen
    (zoals <hostname>) wint de laatste waarde.
    """
    nsmap = {None: NATIVE_NS}
    root = etree.Element(f"{{{NATIVE_NS}}}native", nsmap=nsmap)
    containers = {}  # tag -> ankerelement onder root

    for subtree in subtrees:
        for child in subtree:
            tag = child.tag
            if tag in containers:
                target = containers[tag]
                # Children verplaatsen naar het anker
                for grandchild in list(child):
                    target.append(grandchild)
                # Text-only elementen: laatste wint
                if child.text and child.text.strip():
                    target.text = child.text
            else:
                root.append(child)
                containers[tag] = child
    return root


def _pretty(root) -> str:
    etree.indent(root, space="  ")
    return etree.tostring(
        root, pretty_print=True, xml_declaration=True, encoding="UTF-8"
    ).decode()


def build(device_name: str) -> Path:
    """Bouw de volledige baseline-XML voor device en schrijf naar disk.

    Returns:
        Pad naar het geschreven bestand.
    """
    con = db.connect()
    try:
        data = db.fetch_device_data(con, device_name)
    finally:
        con.close()

    fragment_trees = _load_fragments()
    template_trees = _render_templates(data)

    merged = _merge_native_subtrees(fragment_trees + template_trees)
    xml_text = _pretty(merged)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{device_name}-baseline.xml"
    output_path.write_text(xml_text, encoding="utf-8")
    return output_path

# ----------------------------------------------------------------------
# CLI — `python -m src.builder R1 [--print]`
# ----------------------------------------------------------------------
def main(argv=None):
    """CLI-entrypoint: bouw baseline-XML voor een device.

    Voorbeelden:
        python -m src.builder R1            # schrijf naar disk
        python -m src.builder R1 --print    # schrijf naar disk + dump naar stdout
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="python -m src.builder",
        description="Bouw IOS-XE baseline-XML voor een device uit inventory.db.",
    )
    parser.add_argument(
        "device",
        help="Device-naam zoals in inventory.db (bv. R1).",
    )
    parser.add_argument(
        "-p", "--print",
        action="store_true",
        dest="print_xml",
        help="Print de gegenereerde XML naar stdout (naast schrijven naar disk).",
    )
    args = parser.parse_args(argv)

    output_path = build(args.device)
    print(f"[builder] Baseline geschreven: {output_path}", file=sys.stderr)

    if args.print_xml:
        sys.stdout.write(output_path.read_text(encoding="utf-8"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())