-- A group can have several ranges (the box can be in the infrastructure group while
-- sitting at the end of the network). The existing range of each group moves to the new table.
CREATE TABLE group_ranges (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
    first_ip TEXT NOT NULL,
    last_ip TEXT NOT NULL
);

INSERT INTO group_ranges (group_id, first_ip, last_ip)
SELECT id, first_ip, last_ip FROM groups;

ALTER TABLE groups DROP COLUMN first_ip;
ALTER TABLE groups DROP COLUMN last_ip;
