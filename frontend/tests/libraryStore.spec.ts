import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMockBridge, fixtureGame, fixtureRoot, ok } from '../src/api/mockBridge'
import { useLibraryStore } from '../src/features/library/libraryStore'

describe('library store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('loads cached roots and games and starts scans by task id', async () => {
    const listGroups = vi.fn(async () => ok([{
      id: 'group-rpg', name: 'RPG', gameCount: 1,
      createdAt: 'now', updatedAt: 'now',
    }]))
    const bridge = createMockBridge({
      list_roots: vi.fn(async () => ok([fixtureRoot()])),
      list_games: vi.fn(async () => ok([fixtureGame({ title: 'Alice' })])),
      list_game_groups: listGroups,
      start_scan: vi.fn(async () => ok({ taskId: 'task-1' })),
    })
    const store = useLibraryStore()

    await store.load(bridge)
    await store.scan(bridge, 'root-1', 'full')

    expect(store.games[0].title).toBe('Alice')
    expect(store.groups[0].name).toBe('RPG')
    expect(listGroups).toHaveBeenCalledOnce()
    expect(store.scanTasks['root-1']).toBe('task-1')
  })

  it('commits roots games and groups only when all load requests succeed', async () => {
    const bridge = createMockBridge({
      async list_roots() { return ok([fixtureRoot({ id: 'new-root' })]) },
      async list_games() {
        return { ok: false, error: { code: 'failed', message: 'games failed' } }
      },
      async list_game_groups() {
        return ok([{
          id: 'new-group', name: 'New', gameCount: 0,
          createdAt: 'now', updatedAt: 'now',
        }])
      },
    })
    const store = useLibraryStore()
    store.roots = [fixtureRoot({ id: 'kept-root' })]
    store.games = [fixtureGame({ id: 'kept-game' })]
    store.groups = [{
      id: 'kept-group', name: 'Kept', gameCount: 1,
      createdAt: 'before', updatedAt: 'before',
    }]

    await store.load(bridge)

    expect(store.roots[0].id).toBe('kept-root')
    expect(store.games[0].id).toBe('kept-game')
    expect(store.groups[0].id).toBe('kept-group')
    expect(store.error).toBe('games failed')
  })

  it('resets a deleted concrete group filter but preserves ungrouped', async () => {
    const bridge = createMockBridge({ async list_game_groups() { return ok([]) } })
    const store = useLibraryStore()
    store.groupFilter = 'deleted-group'

    await store.load(bridge)
    expect(store.groupFilter).toBe('all')

    store.groupFilter = 'ungrouped'
    await store.load(bridge)
    expect(store.groupFilter).toBe('ungrouped')
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

  it('shows a stable error when a disabled root is rejected', async () => {
    const bridge = createMockBridge({
      async start_scan() {
        return { ok: false, error: { code: 'root_disabled', message: 'backend text' } }
      },
    })
    const store = useLibraryStore()

    await store.scan(bridge, 'root-1', 'full')

    expect(store.error).toBe('该游戏目录未参与扫描。')
  })
})
