ALTER TABLE games ADD COLUMN version TEXT;
ALTER TABLE games ADD COLUMN detected_version TEXT;
ALTER TABLE games ADD COLUMN version_is_manual INTEGER NOT NULL DEFAULT 0
    CHECK (version_is_manual IN (0, 1));

PRAGMA user_version = 2;
