-- =============================================================
-- Network as Code — SQLite-schema
-- Bron van waarheid voor de configuratie-intentie van IOS-XE.
-- Wordt geconsumeerd door builder.py (Jinja2 -> YANG-XML).
--
-- Conventies:
--   * Booleans als INTEGER met CHECK (SQLite kent geen BOOLEAN).
--   * Subnetmaskers als dotted-quad (matcht ietf-interfaces YANG).
--   * Credentials NIET in de DB; alleen credential_ref naar .env.
-- =============================================================

PRAGMA foreign_keys = ON;

-- -----------------------------------------------------------------
-- DEVICES — netwerktoestellen waarop we deployen.
-- -----------------------------------------------------------------
CREATE TABLE devices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,           -- bv. 'R1'
    mgmt_host       TEXT    NOT NULL,                  -- IP of hostname voor NETCONF
    netconf_port    INTEGER NOT NULL DEFAULT 830,
    platform        TEXT    NOT NULL DEFAULT 'iosxe',
    credential_ref  TEXT    NOT NULL,                  -- key in .env, bv. 'R1_NETCONF'
    description     TEXT
);

-- -----------------------------------------------------------------
-- INTERFACES — taken 4 & 5 uit de payload (Gi2, Gi3).
-- -----------------------------------------------------------------
CREATE TABLE interfaces (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id       INTEGER NOT NULL,
    name            TEXT    NOT NULL,                  -- bv. 'GigabitEthernet2'
    description     TEXT,
    ipv4_address    TEXT    NOT NULL,
    ipv4_netmask    TEXT    NOT NULL,                  -- dotted-quad
    enabled         INTEGER NOT NULL DEFAULT 1
                    CHECK (enabled IN (0, 1)),
    UNIQUE (device_id, name),
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------
-- STATIC_ROUTES — taak 6 uit de payload.
-- -----------------------------------------------------------------
CREATE TABLE static_routes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id       INTEGER NOT NULL,
    dest_prefix     TEXT    NOT NULL,                  -- bv. '10.20.0.0'
    dest_netmask    TEXT    NOT NULL,                  -- dotted-quad
    next_hop        TEXT    NOT NULL,
    description     TEXT,
    UNIQUE (device_id, dest_prefix, dest_netmask, next_hop),
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------
-- VLANS — taak 9 uit de payload.
-- -----------------------------------------------------------------
CREATE TABLE vlans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id       INTEGER NOT NULL,
    vlan_id         INTEGER NOT NULL
                    CHECK (vlan_id BETWEEN 1 AND 4094),
    vlan_name       TEXT    NOT NULL,
    UNIQUE (device_id, vlan_id),
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------
-- DEPLOYMENTS — audit log van elke uitrol.
-- Telkens edit-config wordt aangeroepen, schrijven we hier een rij.
-- git_commit is de hash van de payload-versie die effectief gepusht is.
-- -----------------------------------------------------------------
CREATE TABLE deployments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id       INTEGER NOT NULL,
    started_at      TEXT    NOT NULL,                  -- ISO 8601
    finished_at     TEXT,
    git_commit      TEXT,                              -- bv. '7f3a9c1'
    payload_source  TEXT    NOT NULL,                  -- URL of pad naar baseline.xml
    status          TEXT    NOT NULL
                    CHECK (status IN ('success', 'failure', 'aborted')),
    netconf_reply   TEXT,                              -- samenvatting van <ok/> of <rpc-error>
    error_message   TEXT,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
);

CREATE INDEX idx_deployments_device_started
    ON deployments(device_id, started_at DESC);
