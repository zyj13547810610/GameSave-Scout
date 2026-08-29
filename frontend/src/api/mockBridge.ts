import type { ApiResult, CoverWizardSnapshot, Game, GameGroup, GameSaveScoutBridge, GuidedSaveSession, ScanRoot } from './contracts'

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
    groupIds: [],
    ...overrides,
  }
}

export function fixtureGroup(overrides: Partial<GameGroup> = {}): GameGroup {
  return {
    id: 'group-1',
    name: 'RPG',
    gameCount: 0,
    createdAt: '2026-08-19T00:00:00Z',
    updatedAt: '2026-08-19T00:00:00Z',
    ...overrides,
  }
}

export function createMockBridge(overrides: Partial<GameSaveScoutBridge> = {}): GameSaveScoutBridge {
  let nextGroupId = 1
  let groups: GameGroup[] = []
  const memberships = new Map<string, Set<string>>()

  function groupsWithCounts(): GameGroup[] {
    return groups.map((group) => ({
      ...group,
      gameCount: [...memberships.values()].filter((ids) => ids.has(group.id)).length,
    }))
  }

  const bridge: GameSaveScoutBridge = {
    async bootstrap() {
      return ok({
        appName: 'GameSave Scout', schemaVersion: 4, portable: true, uiScale: 1,
        coverWizardSettings: {
          coverOnlineEnabled: false,
          coverVndbCandidateLimit: 5,
          coverLocalScanCandidateLimit: 10,
          coverOptimizeEnabled: true,
          coverLocalScanDepth: 2,
        },
        libraryScanSettings: { startupQuickScan: true, scanConcurrency: 1 },
        batchSaveSettings: { customRoots: [] },
      })
    },
    async list_rules() { return ok({ items: [], total: 0 }) },
    async get_rule() {
      return { ok: false, error: { code: 'rule_not_found', message: '没有找到对应的规则。' } }
    },
    async validate_rule_draft(input) {
      return ok({
        valid: true, normalizedDraft: input.draft,
        yamlPreview: '', errorCode: null, message: '规则草稿有效。',
      })
    },
    async test_rule_draft() {
      return ok({
        matched: false, summary: '未测试', evidence: [],
        expandedLocations: [], verificationToken: null,
      })
    },
    async save_rule() {
      return { ok: false, error: { code: 'not_implemented', message: '开发 Mock 尚未保存规则。' } }
    },
    async copy_rule() {
      return { ok: false, error: { code: 'not_implemented', message: '开发 Mock 尚未复制规则。' } }
    },
    async set_rule_enabled() {
      return { ok: false, error: { code: 'not_implemented', message: '开发 Mock 尚未修改规则。' } }
    },
    async delete_rule(input) { return ok({ qualifiedId: input.qualifiedId, generation: 1 }) },
    async refresh_rules() {
      return ok({ applied: true, generation: 1, catalogVersion: 'mock', diagnostics: [] })
    },
    async get_game_save_rule_prefill(input) {
      return ok({
        gameId: input.gameId, title: 'Alice', aliases: [], productIds: [],
        locations: [], engineId: null,
      })
    },
    async begin_rule_import() { return ok({ cancelled: true as const }) },
    async confirm_rule_import() {
      return ok({ importedQualifiedIds: [], skippedCount: 0, generation: 1 })
    },
    async export_rule() { return ok({ cancelled: true }) },
    async open_rule_directory() { return ok({ opened: true }) },
    async restore_bundled_ludusavi() {
      return ok({
        available: true, source: 'bundled', bundledSha256: 'mock',
        unavailableReason: null, sourceUrl: 'mock', downloadedAt: '2026-08-23T00:00:00Z',
        sha256: 'mock', etag: null, upstreamCommit: null,
      })
    },
    async set_ui_scale(input) { return ok({ uiScale: input.uiScale }) },
    async set_library_scan_settings(input) { return ok(input) },
    async set_cover_wizard_settings(input) { return ok(input) },
    async add_batch_save_custom_root(input) {
      return ok({ id: 'batch-root-1', ...input })
    },
    async update_batch_save_custom_root(input) {
      return ok({
        id: input.rootId,
        displayPath: 'D:\\Save Archive',
        enabled: input.enabled,
        maxDepth: input.maxDepth,
      })
    },
    async remove_batch_save_custom_root() { return ok({ removed: true }) },
    async choose_batch_save_custom_root() { return ok(null) },
    async start_batch_save_scan() { return ok({ taskId: 'batch-save-task-1' }) },
    async current_batch_save_task() { return ok(null) },
    async list_batch_save_candidates() { return ok({ items: [], total: 0 }) },
    async get_batch_save_candidate() {
      return { ok: false, error: { code: 'batch_candidate_not_found', message: '没有找到对应的批量存档候选。' } }
    },
    async select_batch_save_candidate_ids() { return ok({ candidateIds: [] }) },
    async accept_batch_save_candidates() {
      return ok({ locations: [], recordedCount: 0, unchangedCount: 0 })
    },
    async reassociate_batch_save_candidates(input) {
      return ok({ updatedCount: input.candidateIds.length })
    },
    async ignore_batch_save_candidates(input) {
      return ok({ updatedCount: input.candidateIds.length })
    },
    async restore_batch_save_candidates(input) {
      return ok({ updatedCount: input.candidateIds.length })
    },
    async clear_unavailable_batch_save_candidates(input) {
      return ok({ updatedCount: input.candidateIds.length })
    },
    async create_batch_save_only_game(input) {
      return ok(fixtureGame({
        id: 'save-only-1',
        scanRootId: null,
        relativeDir: null,
        installPath: null,
        title: input.title,
        version: input.version,
        status: 'save_only',
        engineId: input.engineId,
        groupIds: input.groupIds,
      }))
    },
    async rollback_batch_save_only_game() {
      return ok({
        removed: true, restoredCandidateCount: 1,
        removedLocationCount: 1, cleanupWarnings: [],
      })
    },
    async delete_save_only_game() {
      return ok({
        removed: true, restoredCandidateCount: 1,
        removedLocationCount: 1, cleanupWarnings: [],
      })
    },
    async open_batch_save_candidate() { return ok({ opened: true }) },
    async open_batch_save_lookup(input) {
      return ok({ opened: true, url: `https://${input.provider}.example` })
    },
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
        shared: false, usedBy: [],
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
    async list_game_groups() { return ok(groupsWithCounts()) },
    async create_game_group(input) {
      const now = new Date().toISOString()
      const group = fixtureGroup({
        id: `group-${nextGroupId++}`,
        name: input.name.trim(),
        createdAt: now,
        updatedAt: now,
      })
      groups = [...groups, group]
      return ok(group)
    },
    async rename_game_group(input) {
      const current = groups.find((group) => group.id === input.groupId)
      if (!current) {
        return { ok: false, error: { code: 'game_group_not_found', message: '没有找到对应的游戏分组。' } }
      }
      const renamed = { ...current, name: input.name.trim(), updatedAt: new Date().toISOString() }
      groups = groups.map((group) => group.id === input.groupId ? renamed : group)
      return ok(renamed)
    },
    async delete_game_group(input) {
      groups = groups.filter((group) => group.id !== input.groupId)
      for (const ids of memberships.values()) ids.delete(input.groupId)
      return ok({ deleted: true })
    },
    async set_game_groups(input) {
      memberships.set(input.gameId, new Set(input.groupIds))
      return ok(fixtureGame({ id: input.gameId, groupIds: [...input.groupIds] }))
    },
    async update_game_group_memberships(input) {
      let addedCount = 0
      let removedCount = 0
      let unchangedCount = 0
      for (const gameId of [...new Set(input.gameIds)]) {
        const current = memberships.get(gameId) ?? new Set<string>()
        const hasGroup = current.has(input.groupId)
        if (input.mode === 'add' && !hasGroup) {
          current.add(input.groupId)
          addedCount += 1
        } else if (input.mode === 'remove' && hasGroup) {
          current.delete(input.groupId)
          removedCount += 1
        } else {
          unchangedCount += 1
        }
        memberships.set(gameId, current)
      }
      return ok({ addedCount, removedCount, unchangedCount })
    },
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
        source: 'bundled',
        bundledSha256: '1234567890abcdef'.repeat(4),
        unavailableReason: null,
        sourceUrl: 'https://raw.githubusercontent.com/mtkennerly/ludusavi-manifest/master/data/manifest.yaml',
        downloadedAt: '2026-08-12T00:00:00+00:00',
        sha256: '0'.repeat(64),
        etag: null,
        upstreamCommit: null,
      })
    },
    async update_ludusavi() { return ok({ taskId: 'ludusavi-update-1' }) },
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
