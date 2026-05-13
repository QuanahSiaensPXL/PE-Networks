# Network as Code — IOS-XE baseline via SQLite, GitHub & NETCONF

Praktische proef PE Networks (PXL) — Andries Soons en Quanah Siaens — opleveringsdatum **18 mei 2026**.

Eén declaratieve YANG-payload met tien LAB 8.2-taken, gerenderd vanuit een
SQLite-bron, versiebeheerd in GitHub en uitgerold via NETCONF op een
Cisco CSR1000v (week 1-2) en de fysieke labo-router (week 3).

## Architectuur

```
  ┌──────────────────┐    builder.py     ┌──────────────────────┐    deploy.py     ┌─────────────┐
  │  inventory.db    │  ──────────────►  │ R1-baseline.xml      │  ──────────────► │  CSR1000v   │
  │  (SQLite)        │   render+merge    │  (in GitHub)         │    NETCONF       │  / ISR4221  │
  │                  │                   │                      │  edit-config     │             │
  │  • devices       │   ┌──────────┐    │  <config>            │                  │             │
  │  • interfaces    │ + │ fragments│    │   <native>           │                  │             │
  │  • static_routes │   │ (.xml)   │    │     <hostname/>      │                  │             │
  │  • vlans         │ + │ templates│    │     <interface/>...  │                  │             │
  │  • deployments   │   │ (.j2)    │    │   </native>          │                  │             │
  └──────────────────┘   └──────────┘    │  </config>           │                  │             │
                                         └──────────────────────┘                  └─────────────┘
                                              ▲
                                              │
                                          git commit
```

| Laag | Component | Rol |
|------|-----------|-----|
| 1. Bron | `db/schema.sql` + `db/seed.sql` → `inventory.db` | Source of truth voor 3 onderwerpen (interfaces, static routes, VLANs). |
| 2. Artefact | `fragments/`, `templates/`, `src/builder.py` → `configs/generated/R1-baseline.xml` | Versiebeheerde payload met git-commit als immutable referentie. |
| 3. Runtime | Ubuntu 26.04 LTS VM + ncclient + `src/deploy.py` | Voert lock → edit-config → validate → commit → unlock uit. |

## Folderstructuur

```
network-as-code/
├── db/
│   ├── schema.sql            # Tabellen: devices, interfaces, static_routes, vlans, deployments
│   └── seed.sql              # 1 device (R1, .131), 2 interfaces, 1 route, 2 VLANs
├── fragments/                # 6 statische YANG-XML stukjes (één thema per file)
│   ├── 01_hostname.xml
│   ├── 02_banner.xml
│   ├── 03_loopback.xml
│   ├── 07_ntp.xml
│   ├── 08_dns.xml
│   └── 10_ospf.xml
├── templates/                # 3 Jinja-templates die DB-rijen renderen
│   ├── interfaces.xml.j2
│   ├── static_routes.xml.j2
│   └── vlans.xml.j2
├── src/
│   ├── builder.py            # Genereert R1-baseline.xml (Andries)
│   └── deploy.py             # NETCONF-CLI: list/show/build/run/log (Quanah, week 2)
├── configs/generated/
│   └── R1-baseline.xml       # Output van builder.py — gepusht naar GitHub
├── tests/                    # pytest (week 2)
├── .env.example              # Credentials-template (real .env staat in .gitignore)
├── requirements.txt          # ncclient, lxml, Jinja2, click, python-dotenv
└── inventory.db              # Lokaal opgebouwd, NIET in git
```

## Quickstart

```bash
# 1. Virtual env + dependencies
python3 -m venv .venv --system-site-packages    # zie note over lxml hieronder
source .venv/bin/activate
pip install -r requirements_nolxml.txt          # lxml komt via apt (python3-lxml)

# 2. Credentials
cp .env.example .env       # vul wachtwoorden in (.env staat in .gitignore)

# 3. DB opbouwen
sqlite3 inventory.db < db/schema.sql
sqlite3 inventory.db < db/seed.sql

# 4. Payload genereren
python -m src.builder R1
# → configs/generated/R1-baseline.xml (1940 bytes)

# 5. Deploy (volgt in week 2 — Quanah)
python -m src.deploy run R1
```

> **Note over lxml:** Onder Python 3.14 (Ubuntu 26.04) faalt `pip install lxml`
> tegen de C-API. Workaround: gebruik `python3 -m venv --system-site-packages` en
> installeer `python3-lxml` via apt. Details in `Installatielogboek.docx` §7.2.

## Hoe `builder.py` werkt

1. **Lees DB-data** voor het opgegeven device (`devices`, `interfaces`, `static_routes`, `vlans`).
2. **Render Jinja-templates** met die data (`interfaces.xml.j2`, `static_routes.xml.j2`, `vlans.xml.j2`).
   Elke template produceert een `<native xmlns="…Cisco-IOS-XE-native">…</native>`-blok.
3. **Lees statische fragments** uit `fragments/` (alfabetisch). Ook elk een `<native>`-blok.
4. **Merge** alle `<native>`-blokken tot één `<native>`. Top-level kinderen met dezelfde tag (bv. `<interface>`, `<ip>`) worden gegroepeerd: hun grandchildren komen onder één gemeenschappelijke parent.
5. **Wrap** in `<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">`.
6. **Schrijf** naar `configs/generated/<device>-baseline.xml`.

CLI-flags: `--print` om naar stdout te tonen ipv te schrijven.

## inventory.db schema (kort)

| Tabel | Belangrijke kolommen | Bron voor |
|-------|----------------------|-----------|
| `devices` | `name`, `mgmt_host`, `netconf_port`, `credential_ref` | `connect()` in deploy.py |
| `interfaces` | `name`, `description`, `ipv4_address`, `ipv4_netmask`, `enabled` | `templates/interfaces.xml.j2` |
| `static_routes` | `dest_prefix`, `dest_netmask`, `next_hop` | `templates/static_routes.xml.j2` |
| `vlans` | `vlan_id`, `vlan_name` | `templates/vlans.xml.j2` |
| `deployments` | `device_id`, `started_at`, `status`, `git_commit`, `error_message` | Audit-log voor `deploy run` |

Credentials staan **niet** in de DB — `credential_ref` verwijst naar `.env`-keys
(bv. `R1_NETCONF_USERNAME` / `R1_NETCONF_PASSWORD`).

## CLI-commando's

| Commando | Status | Wat het doet |
|----------|--------|--------------|
| `python -m src build R1` | ✅ klaar | Rendert templates + concateneert fragments naar `configs/generated/R1-baseline.xml`. |
| `python -m src list` | ✅ klaar | Toont devices uit `inventory.db` met laatste deploy-status per rij. |
| `python -m src show R1` | ✅ klaar | Device-detail (interfaces, routes, VLANs) + laatste 3 deployments. |
| `python -m src run R1` | ✅ klaar | NETCONF-deploy met capability-aware logica (candidate vs. running, lock/edit/validate/commit/unlock). `--dry-run` valideert zonder commit. |
| `python -m src log R1` | ✅ klaar | Chronologisch overzicht met `--limit` en `--status` filters. |

## Voorbeeld-output

```bash
$ python -m src.builder R1
OK → /home/penet/PE-Networks/configs/generated/R1-baseline.xml  (1940 bytes)

$ head -20 configs/generated/R1-baseline.xml
<?xml version='1.0' encoding='UTF-8'?>
<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <native xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-native">
    <hostname>R1</hostname>
    <banner>
      <motd>
        <banner>Unauthorized access is prohibited!</banner>
      </motd>
    </banner>
    <interface>
      <Loopback>...</Loopback>
      <GigabitEthernet><name>2</name>...</GigabitEthernet>
      <GigabitEthernet><name>3</name>...</GigabitEthernet>
    </interface>
    ...
  </native>
</config>
```

## De 10 LAB 8.2-taken

| # | Onderwerp | Bron | YANG-model |
|---|-----------|------|------------|
| 1 | Hostname | `fragments/01_hostname.xml` | Cisco-IOS-XE-native |
| 2 | Banner MOTD | `fragments/02_banner.xml` | Cisco-IOS-XE-native |
| 3 | Loopback0 + IP | `fragments/03_loopback.xml` | Cisco-IOS-XE-native |
| 4 | GigabitEthernet2 + IP | DB → `interfaces` | Cisco-IOS-XE-native |
| 5 | GigabitEthernet3 + IP | DB → `interfaces` | Cisco-IOS-XE-native |
| 6 | Statische route | DB → `static_routes` | Cisco-IOS-XE-native |
| 7 | NTP-server | `fragments/07_ntp.xml` | Cisco-IOS-XE-native |
| 8 | DNS-server | `fragments/08_dns.xml` | Cisco-IOS-XE-native |
| 9 | VLAN | DB → `vlans` | Cisco-IOS-XE-native |
| 10 | OSPF-routing | `fragments/10_ospf.xml` | Cisco-IOS-XE-native |

## Status

| Onderdeel | Eigenaar | Status |
|-----------|----------|--------|
| Installatielogboek | Andries | ✅ |
| DB-schema + seed | Andries | ✅ |
| 6 fragments | Andries | ✅ |
| 3 templates | Andries | ✅ |
| `builder.py` | Andries | ✅ |
| `R1-baseline.xml` (virtueel) | Andries | ✅ |
| `deploy.py` (CLI + NETCONF) | Quanah / Andries | ✅ |
| Tests voor deploy.py (25 pytest, MockManager) | Andries | ✅ |
| End-to-end test op CSR1000v | Beide | 🚧 zo 10 mei |
| Hardware-test op ISR4221 | Beide | 🚧 di 12 mei |
| Eindrapport | Quanah | 🚧 wo 13 — vr 15 mei |
| Demo | Beide | 🚧 ma 18 mei |

## Planning

- **Week 1 (28 apr — 4 mei):** repo, DB-schema, eerste statische fragments op CSR1000v.
- **Week 2 (5 — 11 mei):** Jinja-templates, builder, deploy-CLI, end-to-end op virtuele router.
- **Week 3 (12 — 18 mei):** migratie naar fysieke labo-router, Dockerfile-bonus, eindrapport, demo.

## Bronnen

- LAB 8.2 — IOS-XE Automatisering met YANG, NETCONF en RESTCONF (PXL).
- Projectvoorstel "Network as Code", versie 2 (28 apr 2026).
- Installatielogboek (Andries Soons, levend document).
