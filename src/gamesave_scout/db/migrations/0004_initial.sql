CREATE TABLE save_scan_candidates (
  id TEXT PRIMARY KEY,
  scope_key TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('directory', 'file', 'glob', 'registry')),
  path_template TEXT NOT NULL,
  display_path TEXT NOT NULL,
  path_key TEXT NOT NULL,
  availability TEXT NOT NULL CHECK (availability IN ('available', 'unavailable', 'unknown')),
  classification TEXT NOT NULL CHECK (classification IN ('installed', 'missing', 'unknown')),
  confidence TEXT NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
  suggested_game_id TEXT REFERENCES games(id) ON DELETE SET NULL,
  suggested_title TEXT,
  external_product_id TEXT,
  engine_id TEXT,
  strong_group_key TEXT,
  review_game_id TEXT REFERENCES games(id) ON DELETE SET NULL,
  review_status TEXT NOT NULL CHECK (review_status IN ('pending', 'recorded', 'ignored', 'save_only')),
  save_location_id TEXT REFERENCES save_locations(id) ON DELETE SET NULL,
  latest_session_id TEXT REFERENCES scan_sessions(id) ON DELETE SET NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(kind, path_key)
);

CREATE INDEX save_scan_candidates_review_idx
ON save_scan_candidates(review_status, availability, confidence, last_seen_at);

CREATE INDEX save_scan_candidates_scope_idx
ON save_scan_candidates(scope_key, last_seen_at);

CREATE TABLE save_scan_observations (
  session_id TEXT NOT NULL REFERENCES scan_sessions(id) ON DELETE CASCADE,
  candidate_id TEXT NOT NULL REFERENCES save_scan_candidates(id) ON DELETE CASCADE,
  sources_json TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  representative_files_json TEXT NOT NULL,
  alternatives_json TEXT NOT NULL,
  matched_file_count INTEGER NOT NULL CHECK (matched_file_count >= 0),
  representatives_truncated INTEGER NOT NULL CHECK (representatives_truncated IN (0, 1)),
  PRIMARY KEY(session_id, candidate_id)
);

PRAGMA user_version = 4;
