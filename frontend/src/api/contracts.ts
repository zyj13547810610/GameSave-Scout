export type ApiError = { code: string; message: string; details?: unknown }

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiError }

export type UiScaleValue = 0.8 | 0.9 | 1 | 1.1 | 1.2

export type CoverWizardSettings = {
  coverOnlineEnabled: boolean
  coverVndbCandidateLimit: number
  coverLocalScanCandidateLimit: number
  coverOptimizeEnabled: boolean
  coverLocalScanDepth: 1 | 2 | 3
}

export type LibraryScanSettings = {
  startupQuickScan: boolean
  scanConcurrency: 1 | 2 | 3 | 4
}

export type BatchSaveCustomRoot = {
  id: string
  displayPath: string
  enabled: boolean
  maxDepth: number
}

export type BatchSaveSettings = {
  customRoots: BatchSaveCustomRoot[]
}

export type BatchSaveCandidate = {
  id: string
  scopeKey: string
  kind: SaveLocationKind
  displayPath: string
  availability: 'available' | 'unavailable' | 'unknown'
  classification: 'installed' | 'missing' | 'unknown'
  confidence: 'high' | 'medium' | 'low'
  suggestedGameId: string | null
  suggestedTitle: string | null
  externalProductId: string | null
  engineId: string | null
  strongGroupKey: string | null
  reviewGameId: string | null
  reviewStatus: 'pending' | 'recorded' | 'ignored' | 'save_only'
  saveLocationId: string | null
  sources: string[]
  evidence: string[]
  representativeFiles: { name: string; size: number; modifiedTimeNs: number }[]
  matchedFileCount: number
  representativesTruncated: boolean
  alternatives: { title: string; reason: string; gameId: string | null }[]
  lookupQuery: string | null
  firstSeenAt: string
  lastSeenAt: string
}

export type BatchSaveCandidateFilters = {
  status?: 'all' | 'pending' | 'installed' | 'missing' | 'unknown' | 'recorded' | 'ignored' | 'unavailable'
  keyword?: string
  confidence?: 'all' | 'high' | 'medium' | 'low'
  source?: 'all' | 'recorded' | 'user' | 'builtin' | 'ludusavi' | 'engine' | 'bounded_scan' | 'registry'
}

export type BatchSaveScanSummary = {
  sessionId: string
  status: 'completed' | 'cancelled' | 'failed' | 'interrupted' | 'unavailable'
  newCount: number
  pendingCount: number
  recordedCount: number
  ignoredCount: number
  unavailableCount: number
  groupCount: number
  inaccessibleScopeCount: number
  truncatedScopeCount: number
  totalEntries: number
  elapsedSeconds: number
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
  appName: 'GameSave Scout'
  schemaVersion: number
  portable: true
  uiScale: UiScaleValue
  coverWizardSettings: CoverWizardSettings
  libraryScanSettings: LibraryScanSettings
  batchSaveSettings: BatchSaveSettings
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

export type SaveOnlyRollbackResult = {
  removed: boolean
  restoredCandidateCount: number
  removedLocationCount: number
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
  source: 'user' | 'builtin' | 'ludusavi' | 'engine'
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
  availability: 'found' | 'predicted'
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
  source: 'bundled' | 'active' | null
  bundledSha256: string | null
  unavailableReason: string | null
  sourceUrl: string | null
  downloadedAt: string | null
  sha256: string | null
  etag: string | null
  upstreamCommit?: string | null
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

export type RuleSource = 'builtin' | 'user'
export type RuleStatus = 'formal' | 'experimental'
export type RuleType = 'engine' | 'save_game' | 'save_engine'
export type EngineCategory = 'general' | 'visual_novel_doujin'

export type RuleDiagnostic = {
  severity: 'info' | 'warning' | 'error'
  code: string
  message: string
  sourceName: string
}

export type RuleSummary = {
  qualifiedId: string
  ruleId: string
  label: string
  ruleType: RuleType
  source: RuleSource
  status: RuleStatus
  enabled: boolean
  priority: number
}

export type EngineRuleEvidenceDraft = {
  op: 'path_exists' | 'glob_exists' | 'glob_magic_at' | 'magic_at' | 'magic_from_end' | 'edge_contains' | 'text_contains' | 'pe_field_contains'
  path: string
  value?: string
  offset?: number
  weight: number
  field?: string
}

export type SaveRuleLocationDraft = {
  kind: SaveLocationKind
  path: string
  category: 'save' | 'config' | 'other'
  confidence: number
  require_existing?: boolean
}

type RuleDraftCommon = {
  version: string
  id: string
  label: string
  status: RuleStatus
  priority: number
  enabled: boolean
  notes: string | null
  references: string[]
}

export type EngineRuleDraft = RuleDraftCommon & {
  type: 'engine'
  category?: EngineCategory | null
  variant?: string
  threshold: number
  all: EngineRuleEvidenceDraft[]
  any: EngineRuleEvidenceDraft[]
  negative: EngineRuleEvidenceDraft[]
}

export type GameSaveRuleDraft = RuleDraftCommon & {
  type: 'save_game'
  titles: string[]
  product_ids: string[]
  locations: SaveRuleLocationDraft[]
}

export type EngineSaveRuleDraft = RuleDraftCommon & {
  type: 'save_engine'
  engine_ids: string[]
  locations: SaveRuleLocationDraft[]
}

export type RuleDraft = EngineRuleDraft | GameSaveRuleDraft | EngineSaveRuleDraft

export type RuleCapabilities = {
  edit: boolean
  copy: boolean
  test: boolean
  toggle: boolean
  delete: boolean
  export: boolean
}

export type RuleDetail = RuleSummary & {
  notes: string | null
  references: string[]
  sourceFile: string
  yamlPreview: string
  draft: RuleDraft
  capabilities: RuleCapabilities
}

export type RuleDraftValidation = {
  valid: boolean
  normalizedDraft: RuleDraft | null
  yamlPreview: string | null
  errorCode: string | null
  message: string
}

export type RuleTestResult = {
  matched: boolean
  summary: string
  evidence: string[]
  expandedLocations: {
    kind: SaveLocationKind
    pathTemplate: string
    displayPath: string
    exists: boolean
    truncated: boolean
    diagnostics: string[]
  }[]
  verificationToken: string | null
}

export type RuleImportDecision = {
  itemId: string
  action: 'import' | 'replace' | 'new_id' | 'skip'
  newRuleId: string | null
}

export type RuleImportPreview = {
  cancelled: false
  sessionId: string
  items: {
    itemId: string
    fileName: string
    valid: boolean
    errors: string[]
    qualifiedId: string | null
    ruleType: RuleType | null
    status: RuleStatus | null
    conflict: 'none' | 'builtin' | 'user' | 'invalid'
    allowedDecisions: RuleImportDecision['action'][]
  }[]
}

export type RuleRefreshResult = {
  applied: boolean
  generation: number
  catalogVersion: string
  diagnostics: RuleDiagnostic[]
}

export type GameSaveRulePrefill = {
  gameId: string
  title: string
  aliases: string[]
  productIds: string[]
  locations: {
    kind: SaveLocationKind
    pathTemplate: string
    category: 'save' | 'config' | 'other'
    confidence: number
  }[]
  engineId: string | null
}

export interface GameSaveScoutBridge {
  bootstrap(): Promise<ApiResult<BootstrapState>>
  list_rules(input: {
    kind: 'all' | 'engine' | 'save'
    source: 'all' | RuleSource
    status: 'all' | RuleStatus
    enabled: 'all' | 'enabled' | 'disabled'
    query: string
    offset: number
    limit: number
  }): Promise<ApiResult<{ items: RuleSummary[]; total: number }>>
  get_rule(input: { qualifiedId: string }): Promise<ApiResult<RuleDetail>>
  validate_rule_draft(input: { draft: RuleDraft }): Promise<ApiResult<RuleDraftValidation>>
  test_rule_draft(input: { draft: RuleDraft; gameId: string }): Promise<ApiResult<RuleTestResult>>
  save_rule(input: {
    originalQualifiedId: string | null
    draft: RuleDraft
    verificationToken: string | null
  }): Promise<ApiResult<{ detail: RuleDetail; generation: number }>>
  copy_rule(input: { qualifiedId: string }): Promise<ApiResult<{ detail: RuleDetail; generation: number }>>
  set_rule_enabled(input: { qualifiedId: string; enabled: boolean }): Promise<ApiResult<{ detail: RuleDetail; generation: number }>>
  delete_rule(input: { qualifiedId: string }): Promise<ApiResult<{ qualifiedId: string; generation: number }>>
  refresh_rules(input: Record<string, never>): Promise<ApiResult<RuleRefreshResult>>
  get_game_save_rule_prefill(input: { gameId: string }): Promise<ApiResult<GameSaveRulePrefill>>
  begin_rule_import(input: Record<string, never>): Promise<ApiResult<RuleImportPreview | { cancelled: true }>>
  confirm_rule_import(input: {
    sessionId: string
    decisions: RuleImportDecision[]
  }): Promise<ApiResult<{ importedQualifiedIds: string[]; skippedCount: number; generation: number }>>
  export_rule(input: { qualifiedId: string }): Promise<ApiResult<{ cancelled: boolean; fileName?: string }>>
  open_rule_directory(input: { target: 'user' | 'legacy' }): Promise<ApiResult<{ opened: boolean }>>
  set_ui_scale(input: { uiScale: UiScaleValue }): Promise<ApiResult<{ uiScale: UiScaleValue }>>
  set_library_scan_settings(input: LibraryScanSettings): Promise<ApiResult<LibraryScanSettings>>
  set_cover_wizard_settings(input: CoverWizardSettings): Promise<ApiResult<CoverWizardSettings>>
  add_batch_save_custom_root(input: {
    displayPath: string
    enabled: boolean
    maxDepth: number
  }): Promise<ApiResult<BatchSaveCustomRoot>>
  update_batch_save_custom_root(input: {
    rootId: string
    enabled: boolean
    maxDepth: number
  }): Promise<ApiResult<BatchSaveCustomRoot>>
  remove_batch_save_custom_root(input: { rootId: string }): Promise<ApiResult<{ removed: boolean }>>
  choose_batch_save_custom_root(): Promise<ApiResult<string | null>>
  start_batch_save_scan(input: {
    standardScopeIds: string[]
    customRootIds: string[]
  }): Promise<ApiResult<{ taskId: string }>>
  current_batch_save_task(): Promise<ApiResult<TaskSnapshot | null>>
  list_batch_save_candidates(input: BatchSaveCandidateFilters & {
    offset: number
    limit: number
  }): Promise<ApiResult<{ items: BatchSaveCandidate[]; total: number }>>
  get_batch_save_candidate(input: { candidateId: string }): Promise<ApiResult<BatchSaveCandidate>>
  select_batch_save_candidate_ids(input: BatchSaveCandidateFilters): Promise<ApiResult<{ candidateIds: string[] }>>
  accept_batch_save_candidates(input: {
    candidateIds: string[]
    confirmRegistry: boolean
  }): Promise<ApiResult<{ locations: SaveLocation[]; recordedCount: number; unchangedCount: number }>>
  reassociate_batch_save_candidates(input: {
    candidateIds: string[]
    gameId: string
  }): Promise<ApiResult<{ updatedCount: number }>>
  ignore_batch_save_candidates(input: { candidateIds: string[] }): Promise<ApiResult<{ updatedCount: number }>>
  restore_batch_save_candidates(input: { candidateIds: string[] }): Promise<ApiResult<{ updatedCount: number }>>
  clear_unavailable_batch_save_candidates(input: { candidateIds: string[] }): Promise<ApiResult<{ updatedCount: number }>>
  create_batch_save_only_game(input: {
    title: string
    version: string | null
    engineId: string | null
    groupIds: string[]
    candidateIds: string[]
    confirmRegistry: boolean
  }): Promise<ApiResult<Game>>
  rollback_batch_save_only_game(input: { candidateId: string }): Promise<ApiResult<SaveOnlyRollbackResult>>
  delete_save_only_game(input: { gameId: string }): Promise<ApiResult<SaveOnlyRollbackResult>>
  open_batch_save_candidate(input: { candidateId: string }): Promise<ApiResult<{ opened: boolean }>>
  open_batch_save_lookup(input: {
    candidateId: string
    provider: 'vndb' | 'dlsite' | '2dfan'
  }): Promise<ApiResult<{ opened: boolean; url: string }>>
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
  restore_bundled_ludusavi(input: Record<string, never>): Promise<ApiResult<LudusaviStatus>>
  choose_directory(): Promise<ApiResult<string | null>>
  task_snapshot(taskId: string): Promise<ApiResult<TaskSnapshot>>
  cancel_task(taskId: string): Promise<ApiResult<{ cancelled: boolean }>>
}
