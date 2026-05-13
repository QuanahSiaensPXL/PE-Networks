# Changelog

Alle materiële wijzigingen aan het Network as Code-project sinds de
ondertekening van projectvoorstel v2 (28 april 2026). Format gebaseerd op
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), gegroepeerd per
datum.

## [Unreleased]

Werk-in-uitvoering richting oplevering 18 mei 2026.

### Quanah's spoor (nog open)

- Eindrapport (5-10 pagina's, 9 secties).

### Hardware-spoor

- ISR4221 mgmt-IP zetten, AAA + NETCONF/YANG enablen.
- Capability-vergelijking virtueel (CSR1000v 16.09.05) vs. fysiek (ISR4221).
- End-to-end deploy van R1-baseline.xml naar de hardware.

---

## [2026-05-08] — Deploy-CLI volledig geïmplementeerd

### Added

- **`src/deploy.py` — vier subcommando's geïmplementeerd** (Quanah's spoor):
  - `list` — devices uit `inventory.db` met laatste deploy-status per rij.
  - `show <device>` — device-detail (interfaces / routes / vlans uit DB)
    plus de laatste 3 deployments.
  - `log <device>` — chronologisch deploy-overzicht met `--limit` en
    `--status {success|failure|aborted}` filters.
  - `run <device>` — NETCONF-deploy met **capability-aware logica**:
    detecteert `:candidate`, `:validate`, `:rollback-on-error`, en kiest
    automatisch tussen candidate-datastore (lock → discard → edit-config
    → validate → commit → unlock) en directe writable-running. `--dry-run`
    valideert maar discard't, vereist `:candidate` (anders: nette abort).
  - Lock-discipline via `try/finally` — target wordt altijd ge-unlocked.
  - Audit-trail: elke deploy schrijft `deployments`-rij met git-commit,
    payload-source, started_at/finished_at, status, netconf_reply en
    error_message. Failures worden óók geregistreerd.
- **`src/db.py` uitgebreid** met deployment-helpers (`list_devices`,
  `get_device`, `insert_deployment`, `update_deployment`,
  `get_recent_deployments`, `get_last_deployment`) — `connect()` en
  `fetch_device_data()` blijven onveranderd.
- **`tests/test_deploy.py` — 25 pytest-tests, allemaal groen** in 1 sec:
  - Pure helpers (`_wrap_in_config`, `_format_status`, `_credentials`,
    `_has_capability`).
  - CLI-tests via `click.testing.CliRunner` voor list / show / log
    (gebruiken `patched_db_path`-fixture).
  - NETCONF-tests met een `FakeManager` die `manager.connect` mockt:
    happy path met candidate, dry-run discard-flow, ISR-achtig toestel
    zonder candidate, edit-config-failure (lock vrijgegeven + DB-rij
    `failure`), missing-payload, unknown-device, dry-run-zonder-candidate.

### Changed

- `_wrap_in_config()` strip XML-declaratie uit de payload voor het binnen
  `<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">` wordt
  geplaatst (declaratie mag niet binnen elementen).

---

## [2026-05-06] — Reproduceerbaarheid + documentatie

### Added

- **Dockerfile + `.dockerignore`** voor reproduceerbare runtime
  (bonus uit projectvoorstel §4.5). Base = `python:3.12-slim`, non-root user
  `penet`, `inventory.db` opgebouwd tijdens build, `ENTRYPOINT python -m
  src.deploy`. Image van ±150 MB.
- **README volledig herschreven** met ASCII-architectuurdiagram,
  folderstructuur als boomdiagram, Docker-quickstart, builder.py-uitleg,
  inventory.db schema-overzicht, status-tabel per onderdeel met eigenaar.

### Changed

- `db/seed.sql` management-IP: `192.168.253.20` → `192.168.253.131`
  (CSR1000v draait momenteel op DHCP). Pas zodra de router naar statisch
  .20 is geconverteerd, terugdraaien.
- `tests/test_db.py` IP-assertion meebewogen met de seed.sql-fix.

---

## [2026-05-05] — Code-skelet en eerste payload

### Added

- **6 statische YANG-fragments** in `fragments/` voor de vaste configuratie-
  taken: hostname, banner MOTD, Loopback0, NTP-server, DNS, OSPF.
  Alle fragmenten gebruiken Cisco-IOS-XE-native als YANG-model.
- **3 Jinja-templates** in `templates/` voor de DB-driven taken:
  interfaces (loopt over `interfaces`-tabel), static_routes, vlans.
- **`src/db.py`** — DB-toegangsmodule (`connect`, `fetch_device_data`).
- **`src/builder.py`** — bouwt `<device>-baseline.xml` met smart-merge:
  top-level containers die in meerdere subtrees voorkomen (`<interface>`,
  `<ip>`) worden samengevoegd, voor text-only elementen wint de laatste
  waarde.
- **`src/deploy.py`** — Click-CLI met `build`-subcommand werkend en stubs
  voor `list/show/run/log` (Quanah's spoor).
- **`src/__init__.py`, `src/__main__.py`** voor `python -m src.deploy`-aanroep.
- **Pytest-suite** in `tests/`: 8 tests op builder.py (well-formed XML,
  smart-merge interface en ip, hostname/VLAN content, unknown-device error)
  en 6 tests op db.py (connect, fetch_device_data, error handling). Plus een
  `check_baseline_netconf.py` dry-run script.
- **`configs/generated/R1-baseline.xml`** — eerste valide baseline-payload,
  versiebeheerd in GitHub als immutable referentie.

### Changed

- `db/seed.sql` management-IP gefixt naar `192.168.253.20` (eerste
  afspraak, vóór de DHCP-realiteit van .131).
- **Template-variabelnamen aligned met DB-schema:** `intf.ip_address →
  intf.ipv4_address`, `route.destination → route.dest_prefix`, `vlan.id →
  vlan.vlan_id` etc. — anders renderden de templates lege strings.
- **Interface-naam extractie:** `<name>{{ intf.name }}</name>` →
  `<name>{{ intf.name | replace('GigabitEthernet', '') }}</name>` zodat
  alleen het cijfer ("2", "3") in de YANG-payload komt.
- **`<no_shutdown>true</no_shutdown>` vervangen** door correcte
  `{% if not intf.enabled %}<shutdown/>{% endif %}` — een presence-leaf
  in Cisco-IOS-XE-native.
- **VLAN-template gerefactord:** elke VLAN krijgt nu zijn eigen
  `<vlan-list>`-blok in plaats van platte `<id>`/`<name>`-paren onder
  één container.

### Fixed

- YANG sub-module namespaces voor NTP, DNS en OSPF die initieel niet
  matchten met IOS-XE 16.09.05.

---

## [2026-04-28] — Project-setup

### Added

- **Projectvoorstel v2** ondertekend met scope van 35/39 LAB 8.2-taken,
  Task 36 als end-to-end showcase, 4-weken-planning met Task 36 als hart.
- **Initiële repo-structuur** op github.com/QuanahSiaensPXL/PE-Networks:
  `db/schema.sql` (5 tabellen: devices, interfaces, static_routes, vlans,
  deployments), `db/seed.sql` (R1, 2 interfaces, 1 route, 2 VLANs),
  `requirements.txt` (ncclient, lxml, Jinja2, click, python-dotenv),
  `.env.example`, `.gitignore`, README-skelet.
- **Runtime-VM opgezet** op Ubuntu Server (later gemigreerd naar 26.04 LTS):
  hostname `penetworks`, statisch IP `192.168.253.10/24` via Netplan,
  Python 3.14.4, virtual environment met `--system-site-packages` voor de
  voorgecompileerde `python3-lxml` (workaround voor lxml-build-issue onder
  Python 3.14). Alle stappen vastgelegd in `Installatielogboek.docx`.
- **CSR1000v** opgezet als virtuele target-router op `192.168.253.131`
  (DHCP), IOS-XE 16.09.05, NETCONF/YANG enabled, candidate-datastore
  feature actief. Capabilities geverifieerd: `:candidate`, `:validate`,
  `:rollback-on-error` allemaal aanwezig.

### Fixed

- `requirements.txt`: lxml uitgesloten bij installatie (apt-versie via
  system-site-packages) om de Python 3.14 wheel-build te omzeilen.
  Definitieve oplossing voor productie volgt via Dockerfile (Python 3.12
  base, geen system-site-packages nodig).
