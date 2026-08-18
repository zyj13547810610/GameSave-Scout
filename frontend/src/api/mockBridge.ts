import type { ApiResult, CoverWizardSnapshot, Game, GameShelfBridge, GuidedSaveSession, ScanRoot } from './contracts'

export function ok<T>(data: T): ApiResult<T> {
  return { ok: true, data }
}

export function fixtureRoot(overrides: Partial<ScanRoot> = {}): ScanRoot {
  return {
    id: 'root-1',
    displayPath: 'D:\\Games',
    pathKey: 'd:\\games',
    enabled: true,
    scanMode: 'children',
    maxDepth: 1,
    exclusions: [],
    lastScannedAt: null,
    lastScanStatus: 'never',
    lastError: null,
    createdAt: '2026-08-12T00:00:00Z',
    ...overrides,
  }
}

export function fixtureGame(overrides: Partial<Game> = {}): Game {
  return {
    id: 'game-1',
    scanRootId: 'root-1',
    relativeDir: 'Alice',
    installPath: 'D:\\Games\\Alice',
    title: 'Alice',
    version: null,
    status: 'installed',
    engineId: null,
    engineVariant: null,
    engineLabel: '未知引擎',
    engineExperimental: false,
    engineIsManual: false,
    detectedEngine: null,
    mainExeRelpath: null,
    mainExeIsManual: false,
    workingDirRelpath: null,
    launchArgs: [],
    environment: {},
    exeArch: 'unknown',
    coverRevision: 0,
    coverThumbUrl: null,
    coverOriginalUrl: null,
    lastLaunchedAt: null,
    missingSince: null,
    ...overrides,
  }
}

export function createMockBridge(overrides: Partial<GameShelfBridge> = {}): GameShelfBridge {
  const bridge: GameShelfBridge = {
    async bootstrap() {
      return ok({
        appName: 'GameShelf', schemaVersion: 2, portable: true, uiScale: 1,
        coverWizardSettings: {
          coverOnlineEnabled: false,
          coverVndbCandidateLimit: 5,
          coverLocalScanCandidateLimit: 10,
        },
        libraryScanSettings: { startupQuickScan: true, scanConcurrency: 1 },
      })
    },
    async set_ui_scale(input) { return ok({ uiScale: input.uiScale }) },
    async set_library_scan_settings(input) { return ok(input) },
    async set_cover_wizard_settings(input) { return ok(input) },
    async start_cover_wizard(input) {
      return ok(fixtureCoverWizard({ includeExisting: input.includeExisting ?? false }))
    },
    async cover_wizard_snapshot() { return ok(fixtureCoverWizard()) },
    async set_cover_wizard_include_existing(input) {
      return ok(fixtureCoverWizard({ includeExisting: input.includeExisting }))
    },
    async list_cover_candidates() { return ok([]) },
    async add_cover_candidate_bytes(input) {
      return ok({
        id: 'candidate-1', gameId: input.gameId, source: input.source,
        sourceLabel: input.source === 'drop' ? '拖放' : '剪贴板',
        displayName: input.fileName, width: 600, height: 900,
        matchKind: 'manual', score: 100, evidence: [], previewUrl: null, vndbId: null,
      })
    },
    async start_cover_vndb_search() { return ok({ taskId: 'cover-task-1' }) },
    async start_cover_shallow_scan() { return ok({ taskId: 'cover-task-1' }) },
    async start_cover_directory_import() { return ok({ taskId: 'cover-task-1' }) },
    async adopt_cover_candidate() {
      return ok({ game: fixtureGame({ coverRevision: 1 }), snapshot: fixtureCoverWizard() })
    },
    async skip_cover_wizard_game() { return ok(fixtureCoverWizard()) },
    async close_cover_wizard() { return ok({ closed: true }) },
    async list_roots() { return ok([]) },
    async add_root(input) { return ok(fixtureRoot({ displayPath: input.displayPath, scanMode: input.scanMode, maxDepth: input.maxDepth, exclusions: input.exclusions })) },
    async update_root(input) { return ok(fixtureRoot({ ...input, id: input.rootId })) },
    async remove_root() { return ok({ removed: true }) },
    async remap_root(input) { return ok(fixtureRoot({ id: input.rootId, displayPath: input.displayPath })) },
    async list_games() { return ok([]) },
    async remove_game_and_exclude() { return ok({ removed: true }) },
    async delete_missing_game() { return ok({ removed: true }) },
    async remove_games(input) {
      const items = [...new Map(input.items.map((item) => [item.gameId, item])).values()]
      return ok({
        installedCount: items.filter((item) => item.expectedStatus === 'installed').length,
        missingCount: items.filter((item) => item.expectedStatus === 'missing').length,
        updatedRootCount: 0,
        cleanupWarnings: [],
      })
    },
    async start_scan() { return ok({ taskId: 'task-1' }) },
    async start_game_reanalysis() { return ok({ taskId: 'reanalysis-task-1' }) },
    async confirm_move(input) { return ok(fixtureGame({ id: input.existingGameId })) },
    async set_game_metadata(input) {
      return ok(fixtureGame({ id: input.gameId, title: input.title, version: input.version }))
    },
    async choose_game_executable() { return ok(null) },
    async set_game_executable(input) { return ok(fixtureGame({ id: input.gameId, mainExeRelpath: input.selectedPath })) },
    async list_engine_options() { return ok([]) },
    async set_game_engine(input) { return ok(fixtureGame({ id: input.gameId, engineId: input.engineId === 'unknown' ? null : input.engineId, engineIsManual: true })) },
    async clear_manual_engine(input) { return ok(fixtureGame({ id: input.gameId, engineIsManual: false })) },
    async update_launch_configuration(input) { return ok(fixtureGame({ id: input.gameId, ...input })) },
    async launch_game(input) { return ok({ gameId: input.gameId, pid: 1, launchedAt: new Date().toISOString() }) },
    async open_install_directory() { return ok({ opened: true }) },
    async choose_cover_file() { return ok(null) },
    async set_cover_from_file(input) { return ok(fixtureGame({ id: input.gameId, coverRevision: 1 })) },
    async set_cover_from_clipboard(input) { return ok(fixtureGame({ id: input.gameId, coverRevision: 1 })) },
    async remove_cover(input) { return ok(fixtureGame({ id: input.gameId, coverRevision: 2 })) },
    async list_save_locations() { return ok([]) },
    async choose_save_path() { return ok(null) },
    async add_manual_save_location(input) {
      return ok({
        id: 'save-1', gameId: input.gameId, kind: input.kind,
        pathTemplate: input.selectedPath, displayPath: input.selectedPath,
        source: 'manual', confidence: 1, evidence: ['用户手动添加'],
        confirmed: true, enabled: true, lastVerifiedAt: null, exists: true,
        matchCount: null, matchesTruncated: false,
      })
    },
    async remove_save_location() { return ok({ removed: true }) },
    async verify_save_locations() { return ok([]) },
    async open_save_location() { return ok({ opened: true }) },
    async suggest_save_locations() { return ok([]) },
    async accept_save_suggestions() { return ok([]) },
    async preview_guided_save_detection(input) {
      return ok({
        gameId: input.gameId,
        gameTitle: 'Alice',
        executable: 'D:\\Games\\Alice\\Alice.exe',
        scopes: [],
        registryTargets: [],
        privacyNotice: '只读取文件路径、大小和修改时间等元数据，不读取或修改存档内容。',
      })
    },
    async start_guided_save_detection(input) {
      return ok(fixtureGuidedSession({ gameId: input.gameId }))
    },
    async current_guided_save_detection() { return ok(null) },
    async guided_save_detection_status() { return ok(fixtureGuidedSession()) },
    async latest_guided_save_detection_for_game() { return ok(null) },
    async mark_guided_save_saved() {
      return ok(fixtureGuidedSession({ status: 'settling', saveMarkedAt: new Date().toISOString() }))
    },
    async stop_guided_save_detection() { return ok(fixtureGuidedSession()) },
    async cancel_guided_save_detection() {
      return ok(fixtureGuidedSession({ status: 'cancelled', finishedAt: new Date().toISOString() }))
    },
    async list_guided_save_discoveries() { return ok([]) },
    async accept_guided_save_discoveries() { return ok([]) },
    async discard_guided_save_detection() { return ok({ discarded: 0 }) },
    async resolve_guided_close() { return ok({ resolved: true }) },
    async ludusavi_status() {
      return ok({
        available: true,
        unavailableReason: null,
        sourceUrl: 'https://raw.githubusercontent.com/mtkennerly/ludusavi-manifest/master/data/manifest.yaml',
        downloadedAt: '2026-08-12T00:00:00+00:00',
        sha256: '0'.repeat(64),
        etag: null,
        upstreamCommit: null,
        customDirectory: 'data\\manifests\\custom',
        customErrors: [],
      })
    },
    async update_ludusavi() { return ok({ taskId: 'ludusavi-update-1' }) },
    async open_custom_manifest_directory() { return ok({ opened: true }) },
    async choose_directory() { return ok(null) },
    async task_snapshot() { return { ok: false, error: { code: 'task_not_found', message: '没有找到对应的后台任务。' } } },
    async cancel_task() { return ok({ cancelled: false }) },
  }
  return Object.assign(bridge, overrides)
}

export function fixtureCoverWizard(
  overrides: Partial<CoverWizardSnapshot> = {},
): CoverWizardSnapshot {
  return {
    id: 'cover-wizard-1',
    queue: [],
    currentGameId: null,
    includeExisting: false,
    sourceOperationActive: false,
    ...overrides,
  }
}

export function fixtureGuidedSession(
  overrides: Partial<GuidedSaveSession> = {},
): GuidedSaveSession {
  return {
    id: 'guided-session-1',
    gameId: 'game-1',
    gameTitle: 'Alice',
    status: 'monitoring',
    startedAt: '2026-08-15T00:00:00+00:00',
    monitoringStartedAt: '2026-08-15T00:00:01+00:00',
    saveMarkedAt: null,
    finishedAt: null,
    changeCount: 0,
    processTrackingDegraded: false,
    overflowedScopes: [],
    truncatedScopes: [],
    closeRequested: false,
    error: null,
    ...overrides,
  }
}
