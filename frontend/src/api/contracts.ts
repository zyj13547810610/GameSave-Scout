export type ApiError = { code: string; message: string; details?: unknown }

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiError }

export type BootstrapState = {
  appName: 'GameShelf'
  schemaVersion: number
  portable: true
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

export type Game = {
  id: string
  scanRootId: string | null
  relativeDir: string | null
  installPath: string | null
  title: string
  status: 'installed' | 'missing' | 'save_only'
  mainExeRelpath: string | null
  mainExeIsManual: boolean
  workingDirRelpath: string | null
  launchArgs: string[]
  environment: Record<string, string>
  exeArch: 'x86' | 'x64' | 'unknown'
  lastLaunchedAt: string | null
  missingSince: string | null
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
  moveSuggestions: Omit<MoveSuggestion, 'sessionId'>[]
}

export interface GameShelfBridge {
  bootstrap(): Promise<ApiResult<BootstrapState>>
  list_roots(): Promise<ApiResult<ScanRoot[]>>
  add_root(input: RootInput): Promise<ApiResult<ScanRoot>>
  update_root(input: RootInput & { rootId: string; enabled: boolean }): Promise<ApiResult<ScanRoot>>
  remove_root(input: { rootId: string }): Promise<ApiResult<{ removed: boolean }>>
  remap_root(input: { rootId: string; displayPath: string }): Promise<ApiResult<ScanRoot>>
  list_games(): Promise<ApiResult<Game[]>>
  start_scan(input: { rootId: string; kind: 'quick' | 'full' }): Promise<ApiResult<{ taskId: string }>>
  confirm_move(input: {
    sessionId: string
    existingGameId: string
    candidateRelativeDir: string
  }): Promise<ApiResult<Game>>
  set_game_title(input: { gameId: string; title: string }): Promise<ApiResult<Game>>
  choose_game_executable(input: { gameId: string }): Promise<ApiResult<string | null>>
  set_game_executable(input: { gameId: string; selectedPath: string }): Promise<ApiResult<Game>>
  update_launch_configuration(input: {
    gameId: string
    workingDirRelpath: string | null
    launchArgs: string[]
    environment: Record<string, string>
  }): Promise<ApiResult<Game>>
  launch_game(input: { gameId: string }): Promise<ApiResult<{ gameId: string; pid: number; launchedAt: string }>>
  open_install_directory(input: { gameId: string }): Promise<ApiResult<{ opened: boolean }>>
  choose_directory(): Promise<ApiResult<string | null>>
  task_snapshot(taskId: string): Promise<ApiResult<TaskSnapshot>>
  cancel_task(taskId: string): Promise<ApiResult<{ cancelled: boolean }>>
}
