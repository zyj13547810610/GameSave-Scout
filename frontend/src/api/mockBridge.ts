import type { ApiResult, Game, GameShelfBridge, ScanRoot } from './contracts'

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
    async bootstrap() { return ok({ appName: 'GameShelf', schemaVersion: 1, portable: true }) },
    async list_roots() { return ok([]) },
    async add_root(input) { return ok(fixtureRoot({ displayPath: input.displayPath, scanMode: input.scanMode, maxDepth: input.maxDepth, exclusions: input.exclusions })) },
    async update_root(input) { return ok(fixtureRoot({ ...input, id: input.rootId })) },
    async remove_root() { return ok({ removed: true }) },
    async remap_root(input) { return ok(fixtureRoot({ id: input.rootId, displayPath: input.displayPath })) },
    async list_games() { return ok([]) },
    async remove_game_and_exclude() { return ok({ removed: true }) },
    async delete_missing_game() { return ok({ removed: true }) },
    async start_scan() { return ok({ taskId: 'task-1' }) },
    async confirm_move(input) { return ok(fixtureGame({ id: input.existingGameId })) },
    async set_game_title(input) { return ok(fixtureGame({ id: input.gameId, title: input.title })) },
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
