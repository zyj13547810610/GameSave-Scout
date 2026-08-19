CREATE TABLE game_groups (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE game_group_memberships (
    game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    group_id TEXT NOT NULL REFERENCES game_groups(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (game_id, group_id)
);

CREATE INDEX game_group_memberships_group_id_idx
ON game_group_memberships (group_id, game_id);

PRAGMA user_version = 3;
