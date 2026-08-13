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

  it('clears the previous scan summary when a new scan starts', async () => {
    const bridge = createMockBridge({
      start_scan: vi.fn(async () => ok({ taskId: 'task-2' })),
    })
    const store = useLibraryStore()
    store.taskSnapshots['root-1'] = {
      id: 'task-1', kind: 'library_scan', status: 'completed',
      progress: { completed: 1, total: null }, message: '扫描完成。', details: {},
      result: null, error: null,
    }

    await store.scan(bridge, 'root-1', 'full')

    expect(store.taskSnapshots['root-1']).toBeUndefined()
    expect(store.scanTasks['root-1']).toBe('task-2')
  })
})
