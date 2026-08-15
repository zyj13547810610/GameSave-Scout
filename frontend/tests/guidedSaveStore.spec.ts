import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GuidedSaveDiscovery, GuidedSaveSession } from '../src/api/contracts'
import { createMockBridge, ok } from '../src/api/mockBridge'
import { useGuidedSaveStore } from '../src/features/saves/guidedSaveStore'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('guidedSaveStore', () => {
  it('does not poll when there is no active or reviewable session', async () => {
    const status = vi.fn()
    const bridge = createMockBridge({
      async current_guided_save_detection() { return ok(null) },
      guided_save_detection_status: status,
    })
    const store = useGuidedSaveStore()

    await store.refreshActive(bridge)
    await vi.advanceTimersByTimeAsync(3000)

    expect(store.session).toBeNull()
    expect(status).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('polls active states once per second and stops at completed', async () => {
    const monitoring = fixtureSession()
    const completed = fixtureSession({
      status: 'completed',
      finishedAt: '2026-08-15T00:01:00+00:00',
    })
    const discovery = fixtureDiscovery()
    const status = vi
      .fn()
      .mockResolvedValueOnce(ok(monitoring))
      .mockResolvedValueOnce(ok(completed))
    const list = vi.fn(async () => ok([discovery]))
    const bridge = createMockBridge({
      async current_guided_save_detection() { return ok(monitoring) },
      guided_save_detection_status: status,
      list_guided_save_discoveries: list,
    })
    const store = useGuidedSaveStore()

    await store.refreshActive(bridge)
    expect(status).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(1)

    await vi.advanceTimersByTimeAsync(1000)

    expect(status).toHaveBeenCalledTimes(2)
    expect(store.session?.status).toBe('completed')
    expect(store.discoveries).toEqual([discovery])
    expect(list).toHaveBeenCalledWith({ sessionId: 'session-1' })
    expect(vi.getTimerCount()).toBe(0)
  })

  it('refreshes immediately after marking a save and does not duplicate timers', async () => {
    const monitoring = fixtureSession()
    const settling = fixtureSession({
      status: 'settling',
      saveMarkedAt: '2026-08-15T00:00:10+00:00',
    })
    const mark = vi.fn(async () => ok(settling))
    const status = vi.fn(async () => ok(settling))
    const bridge = createMockBridge({
      async current_guided_save_detection() { return ok(monitoring) },
      guided_save_detection_status: status,
      mark_guided_save_saved: mark,
    })
    const store = useGuidedSaveStore()
    await store.refreshActive(bridge)

    await store.markSaved(bridge)

    expect(mark).toHaveBeenCalledWith({ sessionId: 'session-1' })
    expect(status).toHaveBeenCalledTimes(2)
    expect(store.session?.status).toBe('settling')
    expect(vi.getTimerCount()).toBe(1)
  })

  it('loads the latest reviewable session only for the requested game', async () => {
    const completed = fixtureSession({ status: 'completed' })
    const latest = vi.fn(async () => ok(completed))
    const bridge = createMockBridge({
      latest_guided_save_detection_for_game: latest,
      async list_guided_save_discoveries() { return ok([fixtureDiscovery()]) },
    })
    const store = useGuidedSaveStore()

    await store.refreshForGame(bridge, 'game-1')

    expect(latest).toHaveBeenCalledWith({ gameId: 'game-1' })
    expect(store.requestedGameId).toBe('game-1')
    expect(store.discoveries).toHaveLength(1)
    expect(vi.getTimerCount()).toBe(0)
  })
})

function fixtureSession(overrides: Partial<GuidedSaveSession> = {}): GuidedSaveSession {
  return {
    id: 'session-1',
    gameId: 'game-1',
    gameTitle: 'Alice',
    status: 'monitoring',
    startedAt: '2026-08-15T00:00:00+00:00',
    monitoringStartedAt: '2026-08-15T00:00:01+00:00',
    saveMarkedAt: null,
    finishedAt: null,
    changeCount: 2,
    processTrackingDegraded: false,
    overflowedScopes: [],
    truncatedScopes: [],
    closeRequested: false,
    error: null,
    ...overrides,
  }
}

function fixtureDiscovery(): GuidedSaveDiscovery {
  return {
    id: 'discovery-1',
    sessionId: 'session-1',
    candidateTemplate: '<game>\\Saves',
    displayPath: 'D:\\Games\\Alice\\Saves',
    kind: 'directory',
    confidence: 0.92,
    evidence: ['保存标记前后发生协调变化'],
    representativeFiles: ['slot1.sav'],
    firstChangedAt: '2026-08-15T00:00:05+00:00',
    lastChangedAt: '2026-08-15T00:00:11+00:00',
    markOffsetMs: 1000,
    affectedByOverflow: false,
    affectedByTruncation: false,
    preselected: true,
    reviewStatus: 'unreviewed',
    saveLocationId: null,
  }
}
