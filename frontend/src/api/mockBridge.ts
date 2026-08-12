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
    mainExeRelpath: null,
    mainExeIsManual: false,
    workingDirRelpath: null,
    launchArgs: [],
    environment: {},
    exeArch: 'unknown',
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
    async start_scan() { return ok({ taskId: 'task-1' }) },
    async confirm_move(input) { return ok(fixtureGame({ id: input.existingGameId })) },
    async set_game_title(input) { return ok(fixtureGame({ id: input.gameId, title: input.title })) },
    async choose_game_executable() { return ok(null) },
    async set_game_executable(input) { return ok(fixtureGame({ id: input.gameId, mainExeRelpath: input.selectedPath })) },
    async update_launch_configuration(input) { return ok(fixtureGame({ id: input.gameId, ...input })) },
    async launch_game(input) { return ok({ gameId: input.gameId, pid: 1, launchedAt: new Date().toISOString() }) },
    async open_install_directory() { return ok({ opened: true }) },
    async choose_directory() { return ok(null) },
    async task_snapshot() { return { ok: false, error: { code: 'task_not_found', message: '没有找到对应的后台任务。' } } },
    async cancel_task() { return ok({ cancelled: false }) },
  }
  return Object.assign(bridge, overrides)
}
