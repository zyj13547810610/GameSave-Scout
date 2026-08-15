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
  CHECK (
    status IN ('missing', 'save_only')
    OR (scan_root_id IS NOT NULL AND relative_dir IS NOT NULL)
  )
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
  status TEXT NOT NULL CHECK (status IN (
    'preparing', 'monitoring', 'settling', 'completed',
    'cancelled', 'failed', 'interrupted'
  )),
  active_slot INTEGER CHECK (active_slot IS NULL OR active_slot = 1),
  started_at TEXT NOT NULL,
  monitoring_started_at TEXT,
  save_marked_at TEXT,
  finished_at TEXT,
  root_pid INTEGER,
  approved_scopes_json TEXT NOT NULL DEFAULT '[]',
  unavailable_scopes_json TEXT NOT NULL DEFAULT '[]',
  overflowed_scopes_json TEXT NOT NULL DEFAULT '[]',
  truncated_scopes_json TEXT NOT NULL DEFAULT '[]',
  process_tracking_degraded INTEGER NOT NULL DEFAULT 0
    CHECK (process_tracking_degraded IN (0, 1)),
  result_summary_json TEXT NOT NULL DEFAULT '{}',
  error_code TEXT,
  error_summary TEXT,
  CHECK (
    (status IN ('preparing', 'monitoring', 'settling') AND active_slot = 1)
    OR (status NOT IN ('preparing', 'monitoring', 'settling') AND active_slot IS NULL)
  )
);

CREATE UNIQUE INDEX save_detection_one_active
  ON save_detection_sessions(active_slot)
  WHERE active_slot = 1;

CREATE TABLE save_discoveries (
  id TEXT PRIMARY KEY,
  scan_session_id TEXT REFERENCES scan_sessions(id) ON DELETE CASCADE,
  detection_session_id TEXT REFERENCES save_detection_sessions(id) ON DELETE CASCADE,
  candidate_template TEXT NOT NULL,
  display_path TEXT NOT NULL,
  path_key TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('directory', 'file', 'registry')),
  suggested_game TEXT,
  engine_id TEXT,
  confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  evidence_json TEXT NOT NULL DEFAULT '[]',
  representative_files_json TEXT NOT NULL DEFAULT '[]',
  first_changed_at TEXT,
  last_changed_at TEXT,
  mark_offset_ms INTEGER,
  affected_by_overflow INTEGER NOT NULL DEFAULT 0
    CHECK (affected_by_overflow IN (0, 1)),
  affected_by_truncation INTEGER NOT NULL DEFAULT 0
    CHECK (affected_by_truncation IN (0, 1)),
  preselected INTEGER NOT NULL DEFAULT 0 CHECK (preselected IN (0, 1)),
  review_status TEXT NOT NULL DEFAULT 'unreviewed'
    CHECK (review_status IN ('unreviewed', 'accepted', 'ignored', 'linked', 'save_only')),
  linked_game_id TEXT REFERENCES games(id) ON DELETE SET NULL,
  save_location_id TEXT REFERENCES save_locations(id) ON DELETE SET NULL,
  CHECK (
    (scan_session_id IS NOT NULL AND detection_session_id IS NULL)
    OR (scan_session_id IS NULL AND detection_session_id IS NOT NULL)
  ),
  UNIQUE(detection_session_id, kind, path_key)
);

CREATE TABLE settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

PRAGMA user_version = 1;
