export type ApiError = { code: string; message: string; details?: unknown }

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiError }

export type UiScaleValue = 0.8 | 0.9 | 1 | 1.1 | 1.2

export type CoverWizardSettings = {
  coverOnlineEnabled: boolean
  coverVndbCandidateLimit: number
  coverLocalScanCandidateLimit: number
}

export type LibraryScanSettings = {
  startupQuickScan: boolean
  scanConcurrency: 1 | 2 | 3 | 4
}

export type CoverCandidateSource =
  | 'vndb'
  | 'clipboard'
  | 'drop'
  | 'shallow_scan'
  | 'cover_directory'

export type CoverWizardQueueItem = {
  gameId: string
  title: string
  version: string | null
  initialHasCover: boolean
  status: 'pending' | 'ready' | 'adopted' | 'skipped' | 'failed'
  candidateCount: number
  error: string | null
}

export type CoverWizardSnapshot = {
  id: string
  queue: CoverWizardQueueItem[]
  currentGameId: string | null
  includeExisting: boolean
  sourceOperationActive: boolean
}

export type CoverCandidate = {
  id: string
  gameId: string
  source: CoverCandidateSource
  sourceLabel: string
  displayName: string
  width: number
  height: number
  matchKind: 'exact' | 'normalized' | 'fuzzy' | 'manual'
  score: number
  evidence: string[]
  previewUrl: string | null
  vndbId: string | null
}

export type CoverUpload = {
  fileName: string
  contentType: string
  dataBase64: string
}

export type BootstrapState = {
  appName: 'GameShelf'
  schemaVersion: number
  portable: true
  uiScale: UiScaleValue
  coverWizardSettings: CoverWizardSettings
  libraryScanSettings: LibraryScanSettings
  assetSessionToken?: string
}

export type ScanRoot = {
  id: string
  displayPath: string
  pathKey: string
  enabled: boolean
  scanMode: 'children' | 'recursive'
  maxDepth: number
  exclusions: string[]
  lastScannedAt: string | null
  lastScanStatus: string
  lastError: string | null
  createdAt: string
}

export type EngineOption = {
  id: string
  label: string
  experimental: boolean
}

export type EngineEvidence = {
  code: string
  detail: string
  path: string | null
  weight: number
}

export type EngineSelection = {
  id: string | null
  label: string
  variant: string | null
  manual: boolean
}

export type EngineDetection = {
  id: string | null
  label: string
  variant: string | null
  confidence: '高' | '中' | '低' | null
  evidence: EngineEvidence[]
  ambiguous: boolean
  experimental: boolean
  alternatives: { id: string; label: string }[]
}

export type Game = {
  id: string
  scanRootId: string | null
  relativeDir: string | null
  installPath: string | null
  title: string
  version: string | null
  status: 'installed' | 'missing' | 'save_only'
  engineId: string | null
  engineVariant: string | null
  engineLabel: string
  engineExperimental: boolean
  engineIsManual: boolean
  detectedEngine: EngineDetection | null
  mainExeRelpath: string | null
  mainExeIsManual: boolean
  workingDirRelpath: string | null
  launchArgs: string[]
  environment: Record<string, string>
  exeArch: 'x86' | 'x64' | 'unknown'
  coverRevision: number
  coverThumbUrl: string | null
  coverOriginalUrl: string | null
  lastLaunchedAt: string | null
  missingSince: string | null
  groupIds: string[]
}

export type GameGroup = {
  id: string
  name: string
  gameCount: number
  createdAt: string
  updatedAt: string
}

export type GroupFilter = 'all' | 'ungrouped' | string

export type GroupMembershipUpdateResult = {
  addedCount: number
  removedCount: number
  unchangedCount: number
}

export type RemovableGameStatus = 'installed' | 'missing'

export type BatchGameRemovalResult = {
  installedCount: number
  missingCount: number
  updatedRootCount: number
  cleanupWarnings: string[]
}

export type SaveLocationKind = 'directory' | 'file' | 'glob' | 'registry'
export type SaveLocationSource = 'manual' | 'dynamic' | 'ludusavi' | 'engine' | 'legacy_scan'

export type SaveLocation = {
  id: string
  gameId: string
  kind: SaveLocationKind
  pathTemplate: string
  displayPath: string
  source: SaveLocationSource
  confidence: number
  evidence: string[]
  confirmed: boolean
  enabled: boolean
  lastVerifiedAt: string | null
  exists: boolean | null
  matchCount: number | null
  matchesTruncated: boolean
}

export type SaveSuggestionEvidence = {
  source: 'custom' | 'ludusavi' | 'engine'
  detail: string
}

export type SaveSuggestion = {
  suggestionId: string
  kind: SaveLocationKind
  pathTemplate: string
  displayPath: string
  source: SaveLocationSource
  confidence: number
  evidence: string[]
  sourceEvidence: SaveSuggestionEvidence[]
  preselected: boolean
  category: 'save' | 'config' | 'other'
  group: 'exact' | 'possible' | 'experimental'
}

export type GuidedSessionStatus =
  | 'preparing'
  | 'monitoring'
  | 'settling'
  | 'completed'
  | 'cancelled'
  | 'failed'
  | 'interrupted'

export type GuidedSaveScope = {
  id: string
  label: string
  displayPath: string
  pathTemplate: string
  source: 'game' | 'documents' | 'saved_games' | 'app_data' | 'local_app_data'
    | 'local_app_data_low' | 'program_data' | 'confirmed' | 'extra'
  defaultSelected: boolean
  available: boolean
  unavailableReason: string | null
}

export type GuidedRegistryTarget = {
  key: string
  source: string
  available: boolean
}

export type GuidedSavePreview = {
  gameId: string
  gameTitle: string
  executable: string
  scopes: GuidedSaveScope[]
  registryTargets: GuidedRegistryTarget[]
  privacyNotice: string
}

export type GuidedSaveSession = {
  id: string
  gameId: string
  gameTitle: string
  status: GuidedSessionStatus
  startedAt: string
  monitoringStartedAt: string | null
  saveMarkedAt: string | null
  finishedAt: string | null
  changeCount: number
  processTrackingDegraded: boolean
  overflowedScopes: string[]
  truncatedScopes: string[]
  closeRequested: boolean
  error: { code: string; message: string } | null
}

export type GuidedSaveDiscovery = {
  id: string
  sessionId: string
  candidateTemplate: string
  displayPath: string
  kind: 'directory' | 'file' | 'registry'
  confidence: number
  evidence: string[]
  representativeFiles: string[]
  firstChangedAt: string | null
  lastChangedAt: string | null
  markOffsetMs: number | null
  affectedByOverflow: boolean
  affectedByTruncation: boolean
  preselected: boolean
  reviewStatus: 'unreviewed' | 'accepted' | 'ignored'
  saveLocationId: string | null
}

export type LudusaviStatus = {
  available: boolean
  unavailableReason: string | null
  sourceUrl: string | null
  downloadedAt: string | null
  sha256: string | null
  etag: string | null
  upstreamCommit?: string | null
  customDirectory: string
  customErrors: { sourceName: string; message: string }[]
}

export type LudusaviUpdateResult = {
  status: 'updated' | 'not_modified' | 'invalid' | 'failed'
  message: string
  metadata: {
    sourceUrl: string
    downloadedAt: string
    sha256: string
    etag: string | null
    upstreamCommit: string | null
  } | null
}

export type RootInput = {
  displayPath: string
  scanMode: 'children' | 'recursive'
  maxDepth: number
  exclusions: string[]
}

export type TaskStatus = 'queued' | 'running' | 'completed' | 'cancelled' | 'failed'

export type TaskSnapshot = {
  id: string
  kind: string
  status: TaskStatus
  progress: { completed: number; total: number | null }
  message: string
  details?: Record<string, string | number | boolean | null>
  result: unknown
  error: ApiError | null
}

export type MoveSuggestion = {
  sessionId: string
  existingGameId: string
  candidateRelativeDir: string
  confidence: number
  evidence: string[]
}

export type ScanResult = {
  sessionId: string
  status: string
  discovered: number
  added: number
  updated: number
  missing: number
  warnings: number
  checked: number
  cacheHits: number
  reanalyzed: number
  fullAnalyses: number
  moveSuggestions: Omit<MoveSuggestion, 'sessionId'>[]
}

export interface GameShelfBridge {
  bootstrap(): Promise<ApiResult<BootstrapState>>
  set_ui_scale(input: { uiScale: UiScaleValue }): Promise<ApiResult<{ uiScale: UiScaleValue }>>
  set_library_scan_settings(input: LibraryScanSettings): Promise<ApiResult<LibraryScanSettings>>
  set_cover_wizard_settings(input: CoverWizardSettings): Promise<ApiResult<CoverWizardSettings>>
  start_cover_wizard(input: { includeExisting?: boolean }): Promise<ApiResult<CoverWizardSnapshot>>
  cover_wizard_snapshot(input: { sessionId: string }): Promise<ApiResult<CoverWizardSnapshot>>
  set_cover_wizard_include_existing(input: {
    sessionId: string
    includeExisting: boolean
  }): Promise<ApiResult<CoverWizardSnapshot>>
  list_cover_candidates(input: {
    sessionId: string
    gameId: string
  }): Promise<ApiResult<CoverCandidate[]>>
  add_cover_candidate_bytes(input: CoverUpload & {
    sessionId: string
    gameId: string
    source: 'clipboard' | 'drop'
  }): Promise<ApiResult<CoverCandidate>>
  start_cover_vndb_search(input: {
    sessionId: string
    gameIds: string[]
    limit: number
  }): Promise<ApiResult<{ taskId: string }>>
  start_cover_shallow_scan(input: {
    sessionId: string
    gameId: string
    limit: number
  }): Promise<ApiResult<{ taskId: string }>>
  start_cover_directory_import(input: {
    sessionId: string
    selectedPath: string
  }): Promise<ApiResult<{ taskId: string }>>
  adopt_cover_candidate(input: {
    sessionId: string
    candidateId: string
  }): Promise<ApiResult<{ game: Game; snapshot: CoverWizardSnapshot }>>
  skip_cover_wizard_game(input: {
    sessionId: string
    gameId: string
  }): Promise<ApiResult<CoverWizardSnapshot>>
  close_cover_wizard(input: { sessionId: string }): Promise<ApiResult<{ closed: boolean }>>
  list_roots(): Promise<ApiResult<ScanRoot[]>>
  add_root(input: RootInput): Promise<ApiResult<ScanRoot>>
  update_root(input: RootInput & { rootId: string; enabled: boolean }): Promise<ApiResult<ScanRoot>>
  remove_root(input: { rootId: string }): Promise<ApiResult<{ removed: boolean }>>
  remap_root(input: { rootId: string; displayPath: string }): Promise<ApiResult<ScanRoot>>
  list_games(): Promise<ApiResult<Game[]>>
  list_game_groups(): Promise<ApiResult<GameGroup[]>>
  create_game_group(input: { name: string }): Promise<ApiResult<GameGroup>>
  rename_game_group(input: { groupId: string; name: string }): Promise<ApiResult<GameGroup>>
  delete_game_group(input: { groupId: string }): Promise<ApiResult<{ deleted: boolean }>>
  set_game_groups(input: { gameId: string; groupIds: string[] }): Promise<ApiResult<Game>>
  update_game_group_memberships(input: {
    groupId: string
    gameIds: string[]
    mode: 'add' | 'remove'
  }): Promise<ApiResult<GroupMembershipUpdateResult>>
  remove_game_and_exclude(input: { gameId: string }): Promise<ApiResult<{ removed: boolean }>>
  delete_missing_game(input: { gameId: string }): Promise<ApiResult<{ removed: boolean }>>
  remove_games(input: {
    items: { gameId: string; expectedStatus: RemovableGameStatus }[]
  }): Promise<ApiResult<BatchGameRemovalResult>>
  start_scan(input: { rootId: string; kind: 'quick' | 'full' }): Promise<ApiResult<{ taskId: string }>>
  start_game_reanalysis(input: { gameId: string }): Promise<ApiResult<{ taskId: string }>>
  confirm_move(input: {
    sessionId: string
    existingGameId: string
    candidateRelativeDir: string
  }): Promise<ApiResult<Game>>
  set_game_metadata(input: {
    gameId: string
    title: string
    version: string | null
  }): Promise<ApiResult<Game>>
  choose_game_executable(input: { gameId: string }): Promise<ApiResult<string | null>>
  set_game_executable(input: { gameId: string; selectedPath: string }): Promise<ApiResult<Game>>
  list_engine_options(): Promise<ApiResult<EngineOption[]>>
  set_game_engine(input: { gameId: string; engineId: string; customLabel?: string }): Promise<ApiResult<Game>>
  clear_manual_engine(input: { gameId: string }): Promise<ApiResult<Game>>
  update_launch_configuration(input: {
    gameId: string
    workingDirRelpath: string | null
    launchArgs: string[]
    environment: Record<string, string>
  }): Promise<ApiResult<Game>>
  launch_game(input: { gameId: string }): Promise<ApiResult<{ gameId: string; pid: number; launchedAt: string }>>
  open_install_directory(input: { gameId: string }): Promise<ApiResult<{ opened: boolean }>>
  choose_cover_file(input: Record<string, never>): Promise<ApiResult<string | null>>
  set_cover_from_file(input: { gameId: string; selectedPath: string }): Promise<ApiResult<Game>>
  set_cover_from_clipboard(input: { gameId: string; pngBase64: string }): Promise<ApiResult<Game>>
  remove_cover(input: { gameId: string }): Promise<ApiResult<Game>>
  list_save_locations(input: { gameId: string }): Promise<ApiResult<SaveLocation[]>>
  choose_save_path(input: { gameId: string; kind: SaveLocationKind }): Promise<ApiResult<string | null>>
  add_manual_save_location(input: {
    gameId: string
    kind: SaveLocationKind
    selectedPath: string
  }): Promise<ApiResult<SaveLocation>>
  remove_save_location(input: { locationId: string }): Promise<ApiResult<{ removed: boolean }>>
  verify_save_locations(input: { gameId: string }): Promise<ApiResult<SaveLocation[]>>
  open_save_location(input: { locationId: string }): Promise<ApiResult<{ opened: boolean }>>
  suggest_save_locations(input: { gameId: string }): Promise<ApiResult<SaveSuggestion[]>>
  accept_save_suggestions(input: {
    gameId: string
    suggestionIds: string[]
    confirmRegistry: boolean
  }): Promise<ApiResult<SaveLocation[]>>
  preview_guided_save_detection(input: { gameId: string }): Promise<ApiResult<GuidedSavePreview>>
  start_guided_save_detection(input: {
    gameId: string
    selectedScopeIds: string[]
    additionalDirectories: string[]
  }): Promise<ApiResult<GuidedSaveSession>>
  current_guided_save_detection(): Promise<ApiResult<GuidedSaveSession | null>>
  guided_save_detection_status(input: { sessionId: string }): Promise<ApiResult<GuidedSaveSession>>
  latest_guided_save_detection_for_game(input: { gameId: string }): Promise<ApiResult<GuidedSaveSession | null>>
  mark_guided_save_saved(input: { sessionId: string }): Promise<ApiResult<GuidedSaveSession>>
  stop_guided_save_detection(input: { sessionId: string }): Promise<ApiResult<GuidedSaveSession>>
  cancel_guided_save_detection(input: { sessionId: string }): Promise<ApiResult<GuidedSaveSession>>
  list_guided_save_discoveries(input: { sessionId: string }): Promise<ApiResult<GuidedSaveDiscovery[]>>
  accept_guided_save_discoveries(input: {
    sessionId: string
    discoveryIds: string[]
    confirmRegistry: boolean
  }): Promise<ApiResult<SaveLocation[]>>
  discard_guided_save_detection(input: { sessionId: string }): Promise<ApiResult<{ discarded: number }>>
  resolve_guided_close(input: {
    resolution: 'return' | 'cancel_and_exit' | 'analyze_and_exit'
  }): Promise<ApiResult<{ resolved: boolean }>>
  ludusavi_status(): Promise<ApiResult<LudusaviStatus>>
  update_ludusavi(input: Record<string, never>): Promise<ApiResult<{ taskId: string }>>
  open_custom_manifest_directory(): Promise<ApiResult<{ opened: boolean }>>
  choose_directory(): Promise<ApiResult<string | null>>
  task_snapshot(taskId: string): Promise<ApiResult<TaskSnapshot>>
  cancel_task(taskId: string): Promise<ApiResult<{ cancelled: boolean }>>
}
