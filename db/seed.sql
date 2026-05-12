-- =============================================================
-- Network as Code — initiële inventory voor R1 (CSR1000v).
-- Idempotent: gebruik samen met `DROP+CREATE` of een verse DB.
-- =============================================================

INSERT INTO devices (name, mgmt_host, netconf_port, platform, credential_ref, description)
VALUES ('R1', '192.168.253.131', 830, 'iosxe', 'R1_NETCONF', 'CSR1000v lab-router (NAT 192.168.253.0/24)');

-- Tabel-driven taken 4 & 5: interfaces
INSERT INTO interfaces (device_id, name, description, ipv4_address, ipv4_netmask, enabled) VALUES
    ((SELECT id FROM devices WHERE name='R1'),
     'GigabitEthernet2', 'Link naar VLAN 10 - data',  '10.10.10.1',  '255.255.255.0', 1),
    ((SELECT id FROM devices WHERE name='R1'),
     'GigabitEthernet3', 'Link naar VLAN 20 - voice', '10.10.20.1',  '255.255.255.0', 1);

-- Tabel-driven taak 6: static route
INSERT INTO static_routes (device_id, dest_prefix, dest_netmask, next_hop, description) VALUES
    ((SELECT id FROM devices WHERE name='R1'),
     '10.99.0.0', '255.255.255.0', '10.10.10.254', 'Route naar managementnetwerk');

-- Tabel-driven taak 9: VLAN
INSERT INTO vlans (device_id, vlan_id, vlan_name) VALUES
    ((SELECT id FROM devices WHERE name='R1'), 10, 'DATA'),
    ((SELECT id FROM devices WHERE name='R1'), 20, 'VOICE');
-- =============================================================
-- R1-HW — fysieke ISR4221 hardware-deploy (12 mei 2026)
-- Mgmt-IP per directe UTP-kabel laptop ↔ Gi0/0/0.
-- IOS-XE 17.03.04a; geen :candidate-datastore → pipeline
-- gebruikt automatisch het writable-running pad met rollback-on-error.
-- =============================================================

INSERT INTO devices (name, mgmt_host, netconf_port, platform, credential_ref, description)
VALUES ('R1-HW', '192.168.253.20', 830, 'iosxe', 'R1HW', 'ISR4221 fysiek (IOS-XE 17.03.04a)');

-- Loopbacks (zelfde adressen als R1 — bewijst platform-onafhankelijkheid van de pipeline)
INSERT INTO interfaces (device_id, name, description, ipv4_address, ipv4_netmask, enabled) VALUES
    ((SELECT id FROM devices WHERE name='R1-HW'),
     'Loopback1', 'Loopback test 1', '10.10.10.1', '255.255.255.255', 1),
    ((SELECT id FROM devices WHERE name='R1-HW'),
     'Loopback2', 'Loopback test 2', '10.10.20.1', '255.255.255.255', 1);

-- Static route (inactief in routing table wegens /32-scenario; staat wel in running-config)
INSERT INTO static_routes (device_id, dest_prefix, dest_netmask, next_hop, description) VALUES
    ((SELECT id FROM devices WHERE name='R1-HW'),
     '192.0.2.0', '255.255.255.0', '10.10.10.254', 'Test static route hardware');
