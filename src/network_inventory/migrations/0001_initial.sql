CREATE TABLE groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    first_ip TEXT NOT NULL,
    last_ip TEXT NOT NULL,
    is_free INTEGER NOT NULL DEFAULT 0 CHECK (is_free IN (0, 1))
);

CREATE TABLE devices (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    group_id INTEGER NOT NULL REFERENCES groups (id) ON DELETE RESTRICT,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE interfaces (
    id INTEGER PRIMARY KEY,
    device_id INTEGER NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    mac TEXT NOT NULL UNIQUE,
    expected_ip TEXT UNIQUE,
    label TEXT NOT NULL DEFAULT ''
);

CREATE TABLE observations (
    mac TEXT PRIMARY KEY,
    ip TEXT NOT NULL,
    vendor TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
