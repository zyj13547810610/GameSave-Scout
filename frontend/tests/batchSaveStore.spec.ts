import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BatchSaveCandidate, TaskSnapshot } from '../src/api/contracts'
import { createMockBridge, ok } from '../src/api/mockBridge'
import { useBatchSaveStore } from '../src/features/saves/batchSaveStore'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
})

afterEach(() => vi.useRealTimers())

describe('batchSaveStore', () => {
  it('restores an active backend task and stops polling at completion', async () => {
    const running = fixtureTask({ status: 'running' })
    const completed = fixtureTask({
      status: 'completed',
      progress: { completed: 1, total: 1 },
      result: { sessionId: 'session-1' },
    })
    const snapshot = vi.fn()
      .mockResolvedValueOnce(ok(running))
      .mockResolvedValueOnce(ok(completed))
    const list = vi.fn(async () => ok({ items: [fixtureCandidate()], total: 1 }))
    const bridge = createMockBridge({
      async current_batch_save_task() { return ok(running) },
      task_snapshot: snapshot,
      list_batch_save_candidates: list,
    })
    const store = useBatchSaveStore()

    await store.open(bridge)
    expect(snapshot).toHaveBeenCalledWith('batch-task-1')
    expect(store.task?.status).toBe('running')
    expect(vi.getTimerCount()).toBe(1)

    await vi.advanceTimersByTimeAsync(500)

    expect(store.task?.status).toBe('completed')
    expect(store.page).toHaveLength(1)
    expect(list).toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('clears only its polling timer without cancelling the backend task', async () => {
    const cancel = vi.fn(async () => ok({ cancelled: true }))
    const bridge = createMockBridge({
      async current_batch_save_task() { return ok(fixtureTask({ status: 'running' })) },
      async task_snapshot() { return ok(fixtureTask({ status: 'running' })) },
      cancel_task: cancel,
    })
    const store = useBatchSaveStore()
    await store.open(bridge)

    store.clearPolling()
    await vi.advanceTimersByTimeAsync(2000)

    expect(cancel).not.toHaveBeenCalled()
    expect(store.task?.status).toBe('running')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('selects at most the current filter result and clears selection explicitly', async () => {
    const select = vi.fn(async () => ok({ candidateIds: ['candidate-1'] }))
    const bridge = createMockBridge({ select_batch_save_candidate_ids: select })
    const store = useBatchSaveStore()
    store.filters.keyword = 'Alice'

    await store.selectCurrentFiltered(bridge)

    expect(select).toHaveBeenCalledWith({
      status: 'all', keyword: 'Alice', confidence: 'all', source: 'all',
    })
    expect([...store.selectedIds]).toEqual(['candidate-1'])
    store.clearSelection()
    expect(store.selectedIds.size).toBe(0)
  })

  it('passes the builtin source filter through list and selection queries', async () => {
    const list = vi.fn(async () => ok({ items: [], total: 0 }))
    const select = vi.fn(async () => ok({ candidateIds: [] }))
    const bridge = createMockBridge({
      list_batch_save_candidates: list,
      select_batch_save_candidate_ids: select,
    })
    const store = useBatchSaveStore()
    store.filters.source = 'builtin'

    await store.loadPage(bridge)
    await store.selectCurrentFiltered(bridge)

    expect(list).toHaveBeenCalledWith(expect.objectContaining({ source: 'builtin' }))
    expect(select).toHaveBeenCalledWith(expect.objectContaining({ source: 'builtin' }))
  })

  it('keeps selection and filters when a review transaction fails', async () => {
    const bridge = createMockBridge({
      async accept_batch_save_candidates() {
        return { ok: false, error: { code: 'stale', message: '候选已变化' } }
      },
    })
    const store = useBatchSaveStore()
    store.filters.keyword = 'Alice'
    store.selectedIds = new Set(['candidate-1'])

    const success = await store.acceptCandidates(bridge, ['candidate-1'], false)

    expect(success).toBe(false)
    expect([...store.selectedIds]).toEqual(['candidate-1'])
    expect(store.filters.keyword).toBe('Alice')
    expect(store.actionError).toBe('候选已变化')
  })
})

function fixtureTask(overrides: Partial<TaskSnapshot> = {}): TaskSnapshot {
  return {
    id: 'batch-task-1', kind: 'batch_save_scan', status: 'queued',
    progress: { completed: 0, total: null }, message: '', result: null, error: null,
    ...overrides,
  }
}

function fixtureCandidate(): BatchSaveCandidate {
  return {
    id: 'candidate-1', scopeKey: 'documents', kind: 'directory', displayPath: 'C:\\Saves',
    availability: 'available', classification: 'unknown', confidence: 'low',
    suggestedGameId: null, suggestedTitle: 'Alice', externalProductId: null,
    engineId: null, strongGroupKey: null, reviewGameId: null, reviewStatus: 'pending',
    saveLocationId: null, sources: ['bounded_scan'], evidence: [], representativeFiles: [],
    matchedFileCount: 0, representativesTruncated: false, alternatives: [],
    lookupQuery: 'Alice', firstSeenAt: 'now', lastSeenAt: 'now',
  }
}
