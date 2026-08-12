CREATE TABLE scan_roots (
  id TEXT PRIMARY KEY,
  display_path TEXT NOT NULL,
  path_key TEXT NOT NULL UNIQUE,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  scan_mode TEXT NOT NULL CHECK (scan_mode IN ('children', 'recursive')),
  max_depth INTEGER NOT NULL DEFAULT 1 CHECK (max_depth >= 1),
  exclusions_json TEXT NOT NULL DEFAULT '[]',
  last_scanned_at TEXT,
  last_scan_status TEXT NOT NULL DEFAULT 'never',
  last_error TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE games (
  id TEXT PRIMARY KEY,
  scan_root_id TEXT REFERENCES scan_roots(id) ON DELETE SET NULL,
  relative_dir TEXT,
  install_path_key TEXT,
  title TEXT NOT NULL,
  detected_title TEXT,
  title_is_manual INTEGER NOT NULL DEFAULT 0 CHECK (title_is_manual IN (0, 1)),
  status TEXT NOT NULL CHECK (status IN ('installed', 'missing', 'save_only')),
  detected_engine_id TEXT,
  detected_engine_variant TEXT,
  engine_id TEXT,
  engine_variant TEXT,
  engine_is_manual INTEGER NOT NULL DEFAULT 0 CHECK (engine_is_manual IN (0, 1)),
  engine_confidence REAL,
  engine_evidence_json TEXT NOT NULL DEFAULT '[]',
  detected_main_exe_relpath TEXT,
  main_exe_relpath TEXT,
  main_exe_is_manual INTEGER NOT NULL DEFAULT 0 CHECK (main_exe_is_manual IN (0, 1)),
  working_dir_relpath TEXT,
  launch_args_json TEXT NOT NULL DEFAULT '[]',
  environment_json TEXT NOT NULL DEFAULT '{}',
  exe_arch TEXT NOT NULL DEFAULT 'unknown' CHECK (exe_arch IN ('x86', 'x64', 'unknown')),
  cover_original_relpath TEXT,
  cover_thumb_relpath TEXT,
  cover_revision INTEGER NOT NULL DEFAULT 0,
  engine_rules_version TEXT,
  added_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_launched_at TEXT,
  missing_since TEXT,
  CHECK (status = 'save_only' OR (scan_root_id IS NOT NULL AND relative_dir IS NOT NULL))
);

CREATE UNIQUE INDEX games_install_path_key_unique
  ON games(install_path_key) WHERE install_path_key IS NOT NULL;
CREATE UNIQUE INDEX games_root_relative_unique
  ON games(scan_root_id, relative_dir)
  WHERE scan_root_id IS NOT NULL AND relative_dir IS NOT NULL;

CREATE TABLE save_locations (
  id TEXT PRIMARY KEY,
  game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('directory', 'file', 'glob', 'registry')),
  path_template TEXT NOT NULL,
  display_path TEXT NOT NULL,
  path_key TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('manual', 'dynamic', 'ludusavi', 'engine', 'legacy_scan')),
  confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  evidence_json TEXT NOT NULL DEFAULT '[]',
  confirmed INTEGER NOT NULL DEFAULT 0 CHECK (confirmed IN (0, 1)),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  last_verified_at TEXT,
  UNIQUE(game_id, kind, path_key)
);

CREATE TABLE scan_sessions (
  id TEXT PRIMARY KEY,
  root_id TEXT REFERENCES scan_roots(id) ON DELETE SET NULL,
  kind TEXT NOT NULL CHECK (kind IN ('library', 'orphan')),
  status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'cancelled', 'failed', 'unavailable')),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  scope_json TEXT NOT NULL DEFAULT '{}',
  counts_json TEXT NOT NULL DEFAULT '{}',
  rules_version TEXT,
  error_summary TEXT
);

CREATE TABLE scan_observations (
  session_id TEXT NOT NULL REFERENCES scan_sessions(id) ON DELETE CASCADE,
  install_path_key TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY(session_id, install_path_key)
);

CREATE TABLE save_detection_sessions (
  id TEXT PRIMARY KEY,
  game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('preparing', 'monitoring', 'settling', 'completed', 'cancelled', 'failed')),
  started_at TEXT NOT NULL,
  save_marked_at TEXT,
  finished_at TEXT,
  monitored_roots_json TEXT NOT NULL DEFAULT '[]',
  overflowed INTEGER NOT NULL DEFAULT 0 CHECK (overflowed IN (0, 1)),
  result_summary_json TEXT NOT NULL DEFAULT '{}',
  error_summary TEXT
);

CREATE TABLE save_discoveries (
  id TEXT PRIMARY KEY,
  scan_session_id TEXT REFERENCES scan_sessions(id) ON DELETE CASCADE,
  detection_session_id TEXT REFERENCES save_detection_sessions(id) ON DELETE CASCADE,
  candidate_template TEXT NOT NULL,
  display_path TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('directory', 'file', 'registry')),
  suggested_game TEXT,
  engine_id TEXT,
  confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  evidence_json TEXT NOT NULL DEFAULT '[]',
  review_status TEXT NOT NULL DEFAULT 'unreviewed'
    CHECK (review_status IN ('unreviewed', 'linked', 'save_only', 'ignored')),
  linked_game_id TEXT REFERENCES games(id) ON DELETE SET NULL,
  CHECK (scan_session_id IS NOT NULL OR detection_session_id IS NOT NULL)
);

CREATE TABLE settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

PRAGMA user_version = 1;
