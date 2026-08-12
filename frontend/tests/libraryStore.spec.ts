import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMockBridge, fixtureGame, fixtureRoot, ok } from '../src/api/mockBridge'
import { useLibraryStore } from '../src/features/library/libraryStore'

describe('library store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('loads cached roots and games and starts scans by task id', async () => {
    const bridge = createMockBridge({
      list_roots: vi.fn(async () => ok([fixtureRoot()])),
      list_games: vi.fn(async () => ok([fixtureGame({ title: 'Alice' })])),
      start_scan: vi.fn(async () => ok({ taskId: 'task-1' })),
    })
    const store = useLibraryStore()

    await store.load(bridge)
    await store.scan(bridge, 'root-1', 'full')

    expect(store.games[0].title).toBe('Alice')
    expect(store.scanTasks['root-1']).toBe('task-1')
  })
})
