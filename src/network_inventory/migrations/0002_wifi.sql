CREATE TABLE wifi_networks (
    id INTEGER PRIMARY KEY,
    ssid TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL DEFAULT '',
    security TEXT NOT NULL CHECK (security IN ('WPA', 'WEP', 'nopass')),
    hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
    notes TEXT NOT NULL DEFAULT ''
);
