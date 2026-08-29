import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  CoverCandidate,
  CoverWizardSnapshot,
  GameSaveScoutBridge,
  TaskSnapshot,
} from '../src/api/contracts'
import { createMockBridge, fixtureCoverWizard, fixtureGame, ok } from '../src/api/mockBridge'
import { useCoverWizardStore } from '../src/features/covers/coverWizardStore'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
})

afterEach(() => vi.useRealTimers())

describe('coverWizardStore', () => {
  it('opens a session and ignores candidates from a stale game response', async () => {
    let resolveOld!: (value: ReturnType<typeof ok<CoverCandidate[]>>) => void
    const old = new Promise<ReturnType<typeof ok<CoverCandidate[]>>>((resolve) => {
      resolveOld = resolve
    })
    const bridge = createMockBridge({
      async start_cover_wizard() { return ok(snapshot('game-1')) },
      list_cover_candidates: vi.fn(async ({ gameId }) => {
        if (gameId === 'game-1') return ok([candidate('one', 'game-1')])
        if (gameId === 'old') return old
        return ok([candidate('two', gameId)])
      }),
    })
    const store = useCoverWizardStore()
    await store.open(bridge)

    const stale = store.selectGame(bridge, 'old')
    await store.selectGame(bridge, 'game-2')
    resolveOld(ok([candidate('old', 'old')]))
    await stale

    expect(store.selectedGameId).toBe('game-2')
    expect(store.candidates.map((item) => item.id)).toEqual(['two'])
    expect(store.selectedCandidateId).toBeNull()
  })

  it('polls source tasks to a terminal state and refreshes the session', async () => {
    const status = vi
      .fn()
      .mockResolvedValueOnce(ok(task('running')))
      .mockResolvedValueOnce(ok(task('completed')))
    const refresh = vi.fn(async () => ok(snapshot('game-1')))
    const bridge = createMockBridge({
      task_snapshot: status,
      cover_wizard_snapshot: refresh,
      async list_cover_candidates() { return ok([]) },
    })
    const store = useCoverWizardStore()
    store.session = snapshot('game-1')
    store.selectedGameId = 'game-1'

    const running = store.startSourceTask(bridge, Promise.resolve(ok({ taskId: 'task-1' })))
    await vi.advanceTimersByTimeAsync(350)
    await running

    expect(status).toHaveBeenCalledTimes(2)
    expect(refresh).toHaveBeenCalledWith({ sessionId: 'wizard-1' })
    expect(store.activeTaskId).toBeNull()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('continues polling a source task when the selected game changes', async () => {
    const status = vi
      .fn()
      .mockResolvedValueOnce(ok(task('running')))
      .mockResolvedValueOnce(ok(task('completed')))
    const refresh = vi.fn(async () => ok(snapshot('game-1')))
    const bridge = createMockBridge({
      task_snapshot: status,
      cover_wizard_snapshot: refresh,
      async list_cover_candidates() { return ok([]) },
    })
    const store = useCoverWizardStore()
    store.session = snapshot('game-1')
    store.selectedGameId = 'game-1'

    await store.startSourceTask(bridge, Promise.resolve(ok({ taskId: 'task-1' })))
    await store.selectGame(bridge, 'game-2')
    await vi.advanceTimersByTimeAsync(350)

    expect(store.taskSnapshot?.status).toBe('completed')
    expect(store.activeTaskId).toBeNull()
    expect(store.selectedGameId).toBe('game-2')
    expect(refresh).toHaveBeenCalledWith({ sessionId: 'wizard-1' })
    expect(vi.getTimerCount()).toBe(0)
  })

  it('keeps the selected candidate when adoption fails', async () => {
    const adopt = vi.fn(async () => ({
      ok: false as const,
      error: { code: 'invalid_cover', message: '保存失败' },
    }))
    const bridge = createMockBridge({
      adopt_cover_candidate: adopt,
    })
    const store = useCoverWizardStore()
    store.session = snapshot('game-1')
    store.selectedGameId = 'game-1'
    store.selectedCandidateId = 'candidate-1'

    expect(await store.adopt(bridge)).toBeNull()
    expect(store.selectedCandidateId).toBe('candidate-1')
    expect(store.error).toBe('保存失败')
    expect(adopt).toHaveBeenCalledWith({
      sessionId: 'wizard-1',
      gameId: 'game-1',
      candidateId: 'candidate-1',
    })
  })

  it('reloads candidates when used directory candidates are toggled', async () => {
    const list = vi.fn(async (
      _input: Parameters<GameSaveScoutBridge['list_cover_candidates']>[0],
    ) => ok([]))
    const bridge = createMockBridge({ list_cover_candidates: list })
    const store = useCoverWizardStore()
    store.session = snapshot('game-1')
    store.selectedGameId = 'game-1'

    await store.loadCandidates(bridge, 'game-1')
    await store.setIncludeUsedDirectoryCandidates(bridge, true)

    expect(list.mock.calls.map(([input]) => input)).toEqual([
      { sessionId: 'wizard-1', gameId: 'game-1', includeUsed: false },
      { sessionId: 'wizard-1', gameId: 'game-1', includeUsed: true },
    ])
    expect(store.includeUsedDirectoryCandidates).toBe(true)
  })

  it('does not overwrite a newly selected game after adoption resolves', async () => {
    let resolveAdopt!: (value: ReturnType<typeof ok<{
      game: ReturnType<typeof fixtureGame>
      snapshot: CoverWizardSnapshot
    }>>) => void
    const pending = new Promise<ReturnType<typeof ok<{
      game: ReturnType<typeof fixtureGame>
      snapshot: CoverWizardSnapshot
    }>>>((resolve) => { resolveAdopt = resolve })
    const adopt = vi.fn(async () => pending)
    const bridge = createMockBridge({
      adopt_cover_candidate: adopt,
      async list_cover_candidates() { return ok([]) },
    })
    const store = useCoverWizardStore()
    store.session = snapshot('game-1')
    store.selectedGameId = 'game-1'
    store.selectedCandidateId = 'candidate-1'

    const adopting = store.adopt(bridge)
    await store.selectGame(bridge, 'game-2')
    resolveAdopt(ok({
      game: fixtureGame({ id: 'game-1' }),
      snapshot: snapshot(null),
    }))

    expect((await adopting)?.id).toBe('game-1')
    expect(store.selectedGameId).toBe('game-2')
    expect(store.session?.currentGameId).toBe('game-1')
    expect(adopt).toHaveBeenCalledWith({
      sessionId: 'wizard-1',
      gameId: 'game-1',
      candidateId: 'candidate-1',
    })
  })

  it('resets the used-candidate toggle when opening and closing sessions', async () => {
    const bridge = createMockBridge({
      async start_cover_wizard() { return ok(snapshot('game-1')) },
      async list_cover_candidates() { return ok([]) },
    })
    const store = useCoverWizardStore()
    store.includeUsedDirectoryCandidates = true

    await store.open(bridge)
    expect(store.includeUsedDirectoryCandidates).toBe(false)
    store.includeUsedDirectoryCandidates = true

    await store.close(bridge)
    expect(store.includeUsedDirectoryCandidates).toBe(false)
  })

  it('cancels an active task, waits for terminal state, then closes', async () => {
    const cancel = vi.fn(async () => ok({ cancelled: true }))
    const close = vi.fn(async () => ok({ closed: true }))
    const bridge = createMockBridge({
      cancel_task: cancel,
      async task_snapshot() { return ok(task('cancelled')) },
      close_cover_wizard: close,
    })
    const store = useCoverWizardStore()
    store.session = snapshot('game-1')
    store.activeTaskId = 'task-1'

    expect(await store.requestClose(bridge)).toBe(true)
    expect(cancel).toHaveBeenCalledWith('task-1')
    expect(close).toHaveBeenCalledWith({ sessionId: 'wizard-1' })
    expect(store.session).toBeNull()
  })
})

function snapshot(currentGameId: string | null): CoverWizardSnapshot {
  return fixtureCoverWizard({
    id: 'wizard-1',
    currentGameId,
    queue: currentGameId
      ? [{
          gameId: currentGameId, title: currentGameId, version: null, initialHasCover: false,
          status: 'ready', candidateCount: 1, error: null,
        }]
      : [],
  })
}

function candidate(id: string, gameId: string): CoverCandidate {
  return {
    id, gameId, source: 'vndb', sourceLabel: 'VNDB', displayName: id,
    width: 600, height: 900, matchKind: 'exact', score: 100,
    evidence: [], previewUrl: `/candidate/${id}`, vndbId: `v-${id}`,
    shared: false, usedBy: [],
  }
}

function task(status: TaskSnapshot['status']): TaskSnapshot {
  return {
    id: 'task-1', kind: 'cover', status,
    progress: { completed: status === 'completed' ? 1 : 0, total: 1 },
    message: '', result: null, error: null,
  }
}
