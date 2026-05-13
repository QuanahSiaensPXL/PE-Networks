"""Tests voor src/builder.py — controleert dat build() een valide
baseline-XML produceert met de verwachte structuur en smart-merge.
"""
from __future__ import annotations
from pathlib import Path
import pytest
from lxml import etree

from src import builder

NATIVE_NS = "http://cisco.com/ns/yang/Cisco-IOS-XE-native"


def _local(tag: str) -> str:
    """Strip de {namespace}-prefix uit een lxml-tag."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def test_build_creates_output_file(patched_db_path):
    output = builder.build("R1")
    assert output.exists()
    assert output.name == "R1-baseline.xml"


def test_build_produces_well_formed_xml(patched_db_path):
    output = builder.build("R1")
    # Mag niet failen
    tree = etree.parse(str(output))
    root = tree.getroot()
    assert _local(root.tag) == "native"
    assert root.nsmap[None] == NATIVE_NS


def test_build_top_level_contains_all_expected_children(patched_db_path):
    """Alle 9 top-level taken moeten één container hebben in de output:
    hostname, banner, interface, ntp, ip, router, vlan.
    (interface combineert taken 3+4+5; ip combineert taken 6+8.)
    """
    output = builder.build("R1")
    root = etree.parse(str(output)).getroot()
    children = [_local(c.tag) for c in root]

    expected = {"hostname", "banner", "interface", "ntp", "ip", "router", "vlan"}
    assert set(children) == expected, f"Onverwachte children: {children}"

    # Geen duplicates op top-level (smart merge moet ze samengevoegd hebben)
    assert len(children) == len(set(children)), f"Duplicates gevonden: {children}"


def test_smart_merge_combines_interface_container(patched_db_path):
    """Fragment 03 (Loopback) en template (2x GigabitEthernet) moeten in
    één <interface>-container samenkomen met 3 children.
    """
    output = builder.build("R1")
    root = etree.parse(str(output)).getroot()

    interfaces = [c for c in root if _local(c.tag) == "interface"]
    assert len(interfaces) == 1, "Verwachte exact 1 <interface>-container na merge"

    children = [_local(c.tag) for c in interfaces[0]]
    assert children.count("Loopback") == 1
    assert children.count("GigabitEthernet") == 2


def test_smart_merge_combines_ip_container(patched_db_path):
    """Fragment 08 (DNS name-server) en template (static_routes route) moeten
    in één <ip>-container samenkomen.
    """
    output = builder.build("R1")
    root = etree.parse(str(output)).getroot()

    ips = [c for c in root if _local(c.tag) == "ip"]
    assert len(ips) == 1, "Verwachte exact 1 <ip>-container na merge"

    children = [_local(c.tag) for c in ips[0]]
    assert "name-server" in children
    assert "route" in children


def test_hostname_text_content_matches_device(patched_db_path):
    output = builder.build("R1")
    root = etree.parse(str(output)).getroot()
    hostname = root.find(f"{{{NATIVE_NS}}}hostname")
    assert hostname is not None
    assert hostname.text == "R1"


@pytest.mark.skip(reason="VLANs uitgefaseerd voor CSR1000v deploy — heractiveren wanneer ISR4221 VLAN-config krijgt")
def test_vlans_render_as_separate_list_entries(patched_db_path):
    """Twee VLANs in DB → twee <vlan-list>-entries (niet één met 2 ids)."""
    output = builder.build("R1")
    root = etree.parse(str(output)).getroot()

    vlan = root.find(f"{{{NATIVE_NS}}}vlan")
    vlan_lists = vlan.findall(f"{{{NATIVE_NS}}}vlan-list")
    assert len(vlan_lists) == 2

    ids = sorted(int(vl.find(f"{{{NATIVE_NS}}}id").text) for vl in vlan_lists)
    assert ids == [10, 20]


def test_build_raises_for_unknown_device(patched_db_path):
    with pytest.raises(ValueError, match="UNKNOWN"):
        builder.build("UNKNOWN")
