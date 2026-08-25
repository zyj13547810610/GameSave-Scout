import { defineStore } from 'pinia'
import type { Game, GameGroup, GameSaveScoutBridge, GroupFilter, MoveSuggestion, RootInput, ScanResult, ScanRoot, TaskSnapshot } from '../../api/contracts'

export const useLibraryStore = defineStore('library', {
  state: () => ({
    roots: [] as ScanRoot[],
    games: [] as Game[],
    groups: [] as GameGroup[],
    loading: false,
    error: '' as string,
    scanTasks: {} as Record<string, string>,
    taskSnapshots: {} as Record<string, TaskSnapshot>,
    moveSuggestions: [] as MoveSuggestion[],
    selectedGameId: null as string | null,
    query: '',
    statusFilter: 'all' as 'all' | Game['status'],
    engineFilter: 'all' as string,
    groupFilter: 'all' as GroupFilter,
  }),
  actions: {
    async load(bridge: GameSaveScoutBridge) {
      this.loading = true
      this.error = ''
      const [roots, games, groups] = await Promise.all([
        bridge.list_roots(),
        bridge.list_games(),
        bridge.list_game_groups(),
      ])
      this.loading = false
      if (!roots.ok) return this.fail(roots.error.message)
      if (!games.ok) return this.fail(games.error.message)
      if (!groups.ok) return this.fail(groups.error.message)
      this.roots = roots.data
      this.games = games.data
      this.groups = groups.data
      if (
        this.groupFilter !== 'all'
        && this.groupFilter !== 'ungrouped'
        && !this.groups.some((group) => group.id === this.groupFilter)
      ) {
        this.groupFilter = 'all'
      }
    },
    async addRoot(bridge: GameSaveScoutBridge, input: RootInput) {
      const result = await bridge.add_root(input)
      if (!result.ok) return this.fail(result.error.message)
      this.roots = [...this.roots.filter((root) => root.id !== result.data.id), result.data]
    },
    async removeRoot(bridge: GameSaveScoutBridge, rootId: string) {
      const result = await bridge.remove_root({ rootId })
      if (!result.ok) return this.fail(result.error.message)
      await this.load(bridge)
    },
    async updateRoot(bridge: GameSaveScoutBridge, root: ScanRoot, enabled: boolean) {
      const result = await bridge.update_root({
        rootId: root.id,
        displayPath: root.displayPath,
        enabled,
        scanMode: root.scanMode,
        maxDepth: root.maxDepth,
        exclusions: root.exclusions,
      })
      if (!result.ok) return this.fail(result.error.message)
      this.roots = this.roots.map((item) => item.id === root.id ? result.data : item)
    },
    async remapRoot(bridge: GameSaveScoutBridge, rootId: string, displayPath: string) {
      const result = await bridge.remap_root({ rootId, displayPath })
      if (!result.ok) return this.fail(result.error.message)
      this.roots = this.roots.map((root) => root.id === rootId ? result.data : root)
    },
    async scan(bridge: GameSaveScoutBridge, rootId: string, kind: 'quick' | 'full') {
      const result = await bridge.start_scan({ rootId, kind })
      if (!result.ok) {
        return this.fail(
          result.error.code === 'root_disabled'
            ? '该游戏目录未参与扫描。'
            : result.error.message,
        )
      }
      delete this.taskSnapshots[rootId]
      this.scanTasks[rootId] = result.data.taskId
      window.setTimeout(() => void this.refreshTask(bridge, rootId), 250)
    },
    async refreshTask(bridge: GameSaveScoutBridge, rootId: string) {
      const taskId = this.scanTasks[rootId]
      if (!taskId) return
      const result = await bridge.task_snapshot(taskId)
      if (!result.ok) return this.fail(result.error.message)
      this.taskSnapshots[rootId] = result.data
      if (result.data.status === 'queued' || result.data.status === 'running') {
        window.setTimeout(() => void this.refreshTask(bridge, rootId), 350)
        return
      }
      delete this.scanTasks[rootId]
      if (result.data.status === 'completed') {
        const scan = result.data.result as ScanResult
        this.moveSuggestions = scan.moveSuggestions.map((item) => ({ ...item, sessionId: scan.sessionId }))
        await this.load(bridge)
        if (scan.status === 'unavailable') {
          this.fail('根目录暂时无法访问，已有游戏状态未改变')
        }
      } else if (result.data.status === 'failed') {
        this.fail(result.data.error?.message ?? '扫描失败，已有游戏状态未改变')
      }
    },
    async cancelScan(bridge: GameSaveScoutBridge, rootId: string) {
      const taskId = this.scanTasks[rootId]
      if (taskId) await bridge.cancel_task(taskId)
    },
    updateGame(game: Game) {
      this.games = this.games.map((item) => item.id === game.id ? game : item)
    },
    async confirmMove(bridge: GameSaveScoutBridge, suggestion: MoveSuggestion) {
      const result = await bridge.confirm_move(suggestion)
      if (!result.ok) return this.fail(result.error.message)
      this.moveSuggestions = this.moveSuggestions.filter((item) => item !== suggestion)
      await this.load(bridge)
    },
    dismissError() { this.error = '' },
    fail(message: string) { this.error = message },
  },
})
