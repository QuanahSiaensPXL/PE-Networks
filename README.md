# Network as Code — IOS-XE baseline via SQLite, GitHub & NETCONF

Praktische proef PE Networks (PXL) — Andries Soons — opleveringsdatum **18 mei 2026**.

Eén declaratieve YANG-payload met tien LAB 8.2-taken, gerenderd vanuit een
SQLite-bron, versiebeheerd in GitHub en uitgerold via NETCONF op een
Cisco CSR1000v (week 1-2) en de fysieke labo-router (week 3).

## Architectuur

| Laag | Component | Rol |
|------|-----------|-----|
| 1. Bron | `db/schema.sql` + `db/seed.sql` -> `inventory.db` | Source of truth voor 3 onderwerpen (interfaces, static routes, VLANs). |
| 2. Artefact | GitHub-repo + `configs/generated/R1-baseline.xml` | Versiebeheerde payload met git-commit als immutable referentie. |
| 3. Runtime | Ubuntu 24.04 VM + ncclient | Voert lock -> edit-config -> validate -> commit -> unlock uit. |

## Quickstart

```bash
# 1. Virtual env + dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Credentials
cp .env.example .env       # vul wachtwoorden in

# 3. DB opbouwen
sqlite3 inventory.db < db/schema.sql
sqlite3 inventory.db < db/seed.sql

# 4. CLI gebruiken (volgt in week 2)
python -m src.deploy list
python -m src.deploy build R1
python -m src.deploy run R1
python -m src.deploy log R1
```

## CLI-commando's

| Commando | Wat het doet |
|----------|--------------|
| `deploy list` | Toont devices uit `inventory.db`. |
| `deploy show R1` | Device-detail + laatste deploy-status. |
| `deploy build R1` | Rendert templates + concateneert fragments naar `configs/generated/R1-baseline.xml`. |
| `deploy run R1` | Haalt baseline.xml van GitHub, voert NETCONF-deploy uit, schrijft `deployments`-rij. |
| `deploy log R1` | Chronologisch overzicht van deploys. |

## De 10 LAB 8.2-taken

| # | Onderwerp | Bron |
|---|-----------|------|
| 1 | Hostname | `fragments/01_hostname.xml` |
| 2 | Banner MOTD | `fragments/02_banner.xml` |
| 3 | Loopback0 + IP | `fragments/03_loopback.xml` |
| 4 | GigabitEthernet2 + IP | DB -> `interfaces` |
| 5 | GigabitEthernet3 + IP | DB -> `interfaces` |
| 6 | Statische route | DB -> `static_routes` |
| 7 | NTP-server | `fragments/07_ntp.xml` |
| 8 | DNS-server | `fragments/08_dns.xml` |
| 9 | VLAN | DB -> `vlans` |
| 10 | OSPF-routing | `fragments/10_ospf.xml` |

## Planning

- **Week 1 (28 apr - 4 mei):** repo + DB-schema + eerste statische fragments op CSR1000v.
- **Week 2 (5 - 11 mei):** Jinja-templates, builder, deploy-CLI, end-to-end op virtuele router.
- **Week 3 (12 - 18 mei):** migratie naar fysieke labo-router, Dockerfile-bonus, eindrapport, demo.
