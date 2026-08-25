import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { GameSaveScoutBridge, RuleDetail, RuleSummary } from '../src/api/contracts'
import { createMockBridge, ok } from '../src/api/mockBridge'
import { useRuleManagementStore } from '../src/features/rules/ruleManagementStore'

function summary(qualifiedId: string, label = qualifiedId): RuleSummary {
  return {
    qualifiedId,
    ruleId: qualifiedId.split(':').at(-1) ?? qualifiedId,
    label,
    ruleType: 'engine',
    source: qualifiedId.startsWith('user:') ? 'user' : 'builtin',
    status: 'formal',
    enabled: true,
    priority: 100,
  }
}

function detail(qualifiedId: string, label = qualifiedId): RuleDetail {
  return {
    ...summary(qualifiedId, label),
    notes: null,
    references: [],
    sourceFile: `${qualifiedId}.yaml`,
    yamlPreview: `id: ${qualifiedId}`,
    draft: {
      version: '1', id: qualifiedId.split(':').at(-1) ?? qualifiedId, label,
      type: 'engine', status: 'formal', priority: 100, enabled: true,
      notes: null, references: [], threshold: 1, all: [], any: [], negative: [],
    },
    capabilities: {
      edit: qualifiedId.startsWith('user:'), copy: true, test: true,
      toggle: qualifiedId.startsWith('user:'), delete: false, export: true,
    },
  }
}

describe('ruleManagementStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useRealTimers()
  })

  it('drops a stale list response that finishes after a newer request', async () => {
    let resolveOld: ((value: ReturnType<typeof ok<{ items: RuleSummary[]; total: number }>>) => void) | undefined
    const bridge = createMockBridge({
      list_rules: vi.fn()
        .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))
        .mockResolvedValueOnce(ok({ items: [summary('builtin:new')], total: 1 })),
    })
    const store = useRuleManagementStore()

    const oldRequest = store.loadList(bridge)
    store.filters.status = 'experimental'
    await store.loadList(bridge)
    resolveOld?.(ok({ items: [summary('builtin:old')], total: 1 }))
    await oldRequest

    expect(store.items.map((item) => item.qualifiedId)).toEqual(['builtin:new'])
  })

  it('debounces query changes by 300ms while enum filters load immediately', async () => {
    vi.useFakeTimers()
    const listRules = vi.fn(async (_input: Parameters<GameSaveScoutBridge['list_rules']>[0]) => ok({ items: [], total: 0 }))
    const bridge = createMockBridge({ list_rules: listRules })
    const store = useRuleManagementStore()

    store.setQuery(bridge, 'kir')
    store.setQuery(bridge, 'kiri')
    expect(listRules).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(299)
    expect(listRules).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(listRules).toHaveBeenCalledTimes(1)
    expect(listRules.mock.calls[0]?.[0].query).toBe('kiri')

    await store.setFilter(bridge, 'source', 'user')
    expect(listRules).toHaveBeenCalledTimes(2)
    expect(listRules.mock.calls[1]?.[0].source).toBe('user')
  })

  it('preserves the prior selection and detail when a new detail fails', async () => {
    const first = detail('builtin:first', 'First')
    const bridge = createMockBridge({
      get_rule: vi.fn()
        .mockResolvedValueOnce(ok(first))
        .mockResolvedValueOnce({ ok: false, error: { code: 'read_failed', message: '读取失败' } }),
    })
    const store = useRuleManagementStore()

    await store.selectRule(bridge, first.qualifiedId)
    await store.selectRule(bridge, 'builtin:second')

    expect(store.selectedQualifiedId).toBe(first.qualifiedId)
    expect(store.detail).toEqual(first)
    expect(store.detailError).toBe('读取失败')
  })

  it('preserves catalog data and exposes diagnostics when refresh is rejected', async () => {
    const store = useRuleManagementStore()
    store.items = [summary('builtin:kept')]
    store.catalogVersion = 'before'
    const bridge = createMockBridge({
      refresh_rules: async () => ok({
        applied: false,
        generation: 8,
        catalogVersion: 'before',
        diagnostics: [{
          severity: 'error', code: 'invalid_yaml', message: '格式错误', sourceName: 'broken.yaml',
        }],
      }),
    })

    await store.refreshRules(bridge)

    expect(store.items.map((item) => item.qualifiedId)).toEqual(['builtin:kept'])
    expect(store.catalogVersion).toBe('before')
    expect(store.diagnostics[0]?.sourceName).toBe('broken.yaml')
    expect(store.refreshError).toContain('未应用')
  })

  it('keeps verification for metadata edits and revokes it for matching edits', async () => {
    const store = useRuleManagementStore()
    store.startNew('engine')
    store.updateDraft({
      ...store.draft!,
      type: 'engine', id: 'kiri', label: 'KiriKiri', threshold: .7,
      all: [{ op: 'path_exists', path: 'data.xp3', weight: 1 }], any: [], negative: [],
    })
    const bridge = createMockBridge({
      async test_rule_draft() {
        return ok({ matched: true, summary: '命中', evidence: ['data.xp3'], expandedLocations: [], verificationToken: 'token-1' })
      },
    })
    await store.testDraft(bridge, 'game-1')
    store.markVerified()
    expect(store.draft?.status).toBe('formal')

    store.updateDraft({ ...store.draft!, notes: '只改备注' })
    expect(store.verificationToken).toBe('token-1')
    expect(store.draft?.status).toBe('formal')

    const engineDraft = store.draft!
    if (engineDraft.type !== 'engine') throw new Error('expected engine draft')
    store.updateDraft({
      ...engineDraft,
      all: [{ ...engineDraft.all[0]!, path: 'other.xp3' }],
    })
    expect(store.verificationToken).toBeNull()
    expect(store.draft?.status).toBe('experimental')
  })

  it('preserves the entire draft and selection after save failure', async () => {
    const store = useRuleManagementStore()
    store.startNew('save_game')
    const draft = {
      ...store.draft!, type: 'save_game' as const, id: 'alice', label: 'Alice', titles: ['Alice'],
      product_ids: [], locations: [{ kind: 'directory' as const, path: '<winDocuments>\\Alice', category: 'save' as const, confidence: .9 }],
    }
    store.updateDraft(draft)
    store.validation = { valid: true, normalizedDraft: draft, yamlPreview: 'id: alice', errorCode: null, message: '有效' }
    const bridge = createMockBridge({
      async save_rule() { return { ok: false, error: { code: 'write_failed', message: '写入失败' } } },
    })

    await store.saveDraft(bridge)

    expect(store.draft).toEqual(draft)
    expect(store.dirty).toBe(true)
    expect(store.mobilePane).toBe('detail')
    expect(store.mutationError).toBe('写入失败')
  })

  it('prefills game save locations with an explicit relaxed existence policy', async () => {
    const store = useRuleManagementStore()
    const bridge = createMockBridge({
      async list_rules() { return ok({ items: [], total: 0 }) },
      async get_game_save_rule_prefill() {
        return ok({
          gameId: 'game-1', title: 'Alice', aliases: [], productIds: [], engineId: 'renpy',
          locations: [{
            kind: 'directory' as const,
            pathTemplate: '<winDocuments>\\Alice',
            category: 'save' as const,
            confidence: 1,
          }],
        })
      },
      async validate_rule_draft({ draft }) {
        return ok({ valid: true, normalizedDraft: draft, yamlPreview: 'id: game_game_1', errorCode: null, message: '有效' })
      },
    })

    await store.openIntent(bridge, { tab: 'save', gameId: 'game-1' })

    if (store.draft?.type !== 'save_game') throw new Error('expected game save draft')
    expect(store.draft.locations[0]?.require_existing).toBe(false)
  })

  it('keeps an import preview after batch failure and selects the first rule after success', async () => {
    const store = useRuleManagementStore()
    store.importPreview = {
      cancelled: false, sessionId: 'session-1',
      items: [{
        itemId: 'one', fileName: 'one.yaml', valid: true, errors: [], qualifiedId: 'user:one',
        ruleType: 'engine', status: 'experimental', conflict: 'none', allowedDecisions: ['import', 'skip'],
      }],
    }
    const failedBridge = createMockBridge({
      async confirm_rule_import() { return { ok: false, error: { code: 'import_failed', message: '整批失败' } } },
    })
    const decisions = [{ itemId: 'one', action: 'import' as const, newRuleId: null }]
    await store.confirmImport(failedBridge, decisions)
    expect(store.importPreview?.sessionId).toBe('session-1')
    expect(store.importError).toBe('整批失败')

    const imported = detail('user:one', 'One')
    const successfulBridge = createMockBridge({
      async confirm_rule_import() { return ok({ importedQualifiedIds: ['user:one'], skippedCount: 0, generation: 9 }) },
      async list_rules() { return ok({ items: [summary('user:one', 'One')], total: 1 }) },
      async get_rule() { return ok(imported) },
    })
    await store.confirmImport(successfulBridge, decisions)
    expect(store.importPreview).toBeNull()
    expect(store.selectedQualifiedId).toBe('user:one')
    expect(store.generation).toBe(9)
  })

  it('reports export success, cancellation and failure without changing the selected rule', async () => {
    const store = useRuleManagementStore()
    store.selectedQualifiedId = 'builtin:kiri'
    const exportRule = vi
      .fn()
      .mockResolvedValueOnce(ok({ cancelled: false, fileName: 'kiri.yaml' }))
      .mockResolvedValueOnce(ok({ cancelled: true }))
      .mockResolvedValueOnce({ ok: false, error: { code: 'export_failed', message: '导出失败' } })
    const bridge = createMockBridge({ export_rule: exportRule })

    await store.exportRule(bridge, 'builtin:kiri')
    expect(store.notice).toContain('kiri.yaml')
    await store.exportRule(bridge, 'builtin:kiri')
    expect(store.notice).toContain('取消导出')
    await store.exportRule(bridge, 'builtin:kiri')
    expect(store.mutationError).toBe('导出失败')
    expect(store.selectedQualifiedId).toBe('builtin:kiri')
  })

  it('returns to the list and requests focus on the neighboring rule after deletion', async () => {
    const store = useRuleManagementStore()
    const removed = detail('user:removed', 'Removed')
    const neighbor = detail('user:neighbor', 'Neighbor')
    store.items = [summary('user:removed', 'Removed'), summary('user:neighbor', 'Neighbor')]
    store.total = 2
    store.selectedQualifiedId = removed.qualifiedId
    store.detail = removed
    store.mobilePane = 'detail'
    const bridge = createMockBridge({
      async delete_rule() { return ok({ qualifiedId: removed.qualifiedId, generation: 11 }) },
      async get_rule() { return ok(neighbor) },
    })

    await store.deleteRule(bridge, removed.qualifiedId)

    expect(store.selectedQualifiedId).toBe(neighbor.qualifiedId)
    expect(store.mobilePane).toBe('list')
    expect(store.focusQualifiedId).toBe(neighbor.qualifiedId)
  })
})
