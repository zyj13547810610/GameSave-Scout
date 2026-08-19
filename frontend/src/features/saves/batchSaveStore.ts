import { defineStore } from 'pinia'
import type {
  BatchSaveCandidate,
  GameShelfBridge,
  TaskSnapshot,
} from '../../api/contracts'

export type BatchSaveFilters = {
  status: 'all' | 'pending' | 'installed' | 'missing' | 'unknown' | 'recorded' | 'ignored' | 'unavailable'
  keyword: string
  confidence: 'all' | 'high' | 'medium' | 'low'
  source: 'all' | 'recorded' | 'custom' | 'ludusavi' | 'engine' | 'bounded_scan' | 'registry'
  offset: number
  limit: number
}

const activeStatuses = new Set<TaskSnapshot['status']>(['queued', 'running'])

export const useBatchSaveStore = defineStore('batch-save', {
  state: () => ({
    task: null as TaskSnapshot | null,
    page: [] as BatchSaveCandidate[],
    total: 0,
    selectedIds: new Set<string>(),
    selectedCandidateDetails: {} as Record<string, BatchSaveCandidate>,
    filters: {
      status: 'all',
      keyword: '',
      confidence: 'all',
      source: 'all',
      offset: 0,
      limit: 50,
    } as BatchSaveFilters,
    loading: false,
    actionBusy: false,
    actionError: '',
    error: '',
    notice: '',
    pollTimer: null as number | null,
    pollRevision: 0,
  }),
  actions: {
    clearPolling() {
      this.pollRevision += 1
      if (this.pollTimer !== null) window.clearTimeout(this.pollTimer)
      this.pollTimer = null
    },
    async refreshCurrent(bridge: GameShelfBridge) {
      const result = await bridge.current_batch_save_task()
      if (!result.ok) return this.fail(result.error.message)
      this.task = result.data
    },
    async open(bridge: GameShelfBridge) {
      this.clearPolling()
      this.error = ''
      await this.refreshCurrent(bridge)
      await this.loadPage(bridge)
      if (this.task && activeStatuses.has(this.task.status)) {
        await this.startPolling(bridge)
      }
    },
    async startScan(
      bridge: GameShelfBridge,
      standardScopeIds: string[],
      customRootIds: string[],
    ) {
      this.actionBusy = true
      this.error = ''
      this.notice = ''
      this.actionError = ''
      const result = await bridge.start_batch_save_scan({ standardScopeIds, customRootIds })
      this.actionBusy = false
      if (!result.ok) return this.fail(result.error.message)
      const snapshot = await bridge.task_snapshot(result.data.taskId)
      if (!snapshot.ok) return this.fail(snapshot.error.message)
      this.task = snapshot.data
      await this.startPolling(bridge)
    },
    async startPolling(bridge: GameShelfBridge) {
      this.clearPolling()
      const revision = this.pollRevision
      await this.pollTask(bridge, revision)
    },
    async pollTask(bridge: GameShelfBridge, revision?: number) {
      const activeRevision = revision ?? this.pollRevision
      const taskId = this.task?.id
      if (!taskId) return
      const result = await bridge.task_snapshot(taskId)
      if (activeRevision !== this.pollRevision) return
      if (!result.ok) return this.fail(result.error.message)
      this.task = result.data
      if (activeStatuses.has(result.data.status)) {
        this.pollTimer = window.setTimeout(
          () => void this.pollTask(bridge, activeRevision),
          500,
        )
        return
      }
      this.pollTimer = null
      if (result.data.status === 'failed') {
        this.error = result.data.error?.message ?? '批量存档扫描失败。'
      } else if (result.data.status === 'cancelled') {
        this.notice = '扫描已取消，已发现的候选仍会保留。'
      }
      await this.loadPage(bridge)
    },
    async cancelScan(bridge: GameShelfBridge) {
      const taskId = this.task?.id
      if (!taskId || !activeStatuses.has(this.task?.status ?? 'completed')) return
      this.actionBusy = true
      const result = await bridge.cancel_task(taskId)
      this.actionBusy = false
      if (!result.ok) return this.fail(result.error.message)
      await this.pollTask(bridge)
    },
    async loadPage(bridge: GameShelfBridge) {
      this.loading = true
      const result = await bridge.list_batch_save_candidates({ ...this.filters })
      this.loading = false
      if (!result.ok) return this.fail(result.error.message)
      this.page = result.data.items
      this.total = result.data.total
      for (const candidate of this.page) {
        if (this.selectedIds.has(candidate.id)) {
          this.selectedCandidateDetails[candidate.id] = candidate
        }
      }
    },
    async selectCurrentFiltered(bridge: GameShelfBridge) {
      this.actionBusy = true
      const result = await bridge.select_batch_save_candidate_ids({
        status: this.filters.status,
        keyword: this.filters.keyword,
        confidence: this.filters.confidence,
        source: this.filters.source,
      })
      this.actionBusy = false
      if (!result.ok) return this.fail(result.error.message)
      this.selectedIds = new Set(result.data.candidateIds)
      const details = await Promise.all(result.data.candidateIds.map((candidateId) => (
        bridge.get_batch_save_candidate({ candidateId })
      )))
      this.selectedCandidateDetails = Object.fromEntries(
        details
          .filter((item) => item.ok)
          .map((item) => [item.data.id, item.data]),
      )
    },
    clearSelection() {
      this.selectedIds = new Set()
      this.selectedCandidateDetails = {}
    },
    toggleSelection(candidate: BatchSaveCandidate) {
      const next = new Set(this.selectedIds)
      const details = { ...this.selectedCandidateDetails }
      if (next.has(candidate.id)) {
        next.delete(candidate.id)
        delete details[candidate.id]
      } else {
        next.add(candidate.id)
        details[candidate.id] = candidate
      }
      this.selectedIds = next
      this.selectedCandidateDetails = details
    },
    async acceptCandidates(
      bridge: GameShelfBridge,
      candidateIds: string[],
      confirmRegistry: boolean,
    ) {
      this.actionBusy = true
      this.actionError = ''
      const result = await bridge.accept_batch_save_candidates({
        candidateIds,
        confirmRegistry,
      })
      this.actionBusy = false
      if (!result.ok) {
        this.actionError = result.error.message
        return false
      }
      this.notice = `已添加 ${result.data.recordedCount} 个存档位置，${result.data.unchangedCount} 个位置未变化。`
      await this.finishCandidateAction(bridge, candidateIds)
      return true
    },
    async ignoreCandidates(bridge: GameShelfBridge, candidateIds: string[]) {
      return this.updateCandidateStatus(
        bridge,
        candidateIds,
        () => bridge.ignore_batch_save_candidates({ candidateIds }),
        '已忽略所选候选。',
      )
    },
    async restoreCandidates(bridge: GameShelfBridge, candidateIds: string[]) {
      return this.updateCandidateStatus(
        bridge,
        candidateIds,
        () => bridge.restore_batch_save_candidates({ candidateIds }),
        '已恢复所选候选。',
      )
    },
    async clearUnavailable(bridge: GameShelfBridge, candidateIds: string[]) {
      return this.updateCandidateStatus(
        bridge,
        candidateIds,
        () => bridge.clear_unavailable_batch_save_candidates({ candidateIds }),
        '已清除不可用候选历史；磁盘文件和正式存档位置未改动。',
      )
    },
    async updateCandidateStatus(
      bridge: GameShelfBridge,
      candidateIds: string[],
      operation: () => ReturnType<
        GameShelfBridge['ignore_batch_save_candidates']
      >,
      notice: string,
    ) {
      this.actionBusy = true
      this.actionError = ''
      const result = await operation()
      this.actionBusy = false
      if (!result.ok) {
        this.actionError = result.error.message
        return false
      }
      this.notice = notice
      await this.finishCandidateAction(bridge, candidateIds)
      return true
    },
    async finishCandidateAction(bridge: GameShelfBridge, candidateIds: string[]) {
      const processed = new Set(candidateIds)
      this.selectedIds = new Set([...this.selectedIds].filter((id) => !processed.has(id)))
      this.selectedCandidateDetails = Object.fromEntries(
        Object.entries(this.selectedCandidateDetails).filter(([id]) => !processed.has(id)),
      )
      await this.loadPage(bridge)
    },
    fail(message: string) {
      this.clearPolling()
      this.loading = false
      this.actionBusy = false
      this.error = message
    },
  },
})
