import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { GameShelfBridge, RuleDetail, RuleSummary } from '../src/api/contracts'
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
    const listRules = vi.fn(async (_input: Parameters<GameShelfBridge['list_rules']>[0]) => ok({ items: [], total: 0 }))
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
})
