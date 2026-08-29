import { defineStore } from 'pinia'
import type {
  ApiResult,
  CoverCandidate,
  CoverUpload,
  CoverWizardSnapshot,
  Game,
  GameSaveScoutBridge,
  TaskSnapshot,
} from '../../api/contracts'

const POLL_INTERVAL_MS = 350
const activeTaskStatuses = new Set<TaskSnapshot['status']>(['queued', 'running'])
type SourceTaskResult = ApiResult<{ taskId: string }>

export const useCoverWizardStore = defineStore('cover-wizard', {
  state: () => ({
    session: null as CoverWizardSnapshot | null,
    candidates: [] as CoverCandidate[],
    selectedGameId: null as string | null,
    selectedCandidateId: null as string | null,
    activeTaskId: null as string | null,
    taskSnapshot: null as TaskSnapshot | null,
    pollTimer: null as number | null,
    requestRevision: 0,
    pollRevision: 0,
    error: '',
    sourceError: '',
    closing: false,
    includeUsedDirectoryCandidates: false,
  }),
  actions: {
    clearPolling() {
      this.requestRevision += 1
      this.pollRevision += 1
      if (this.pollTimer !== null) window.clearTimeout(this.pollTimer)
      this.pollTimer = null
    },
    async open(bridge: GameSaveScoutBridge, includeExisting = false) {
      this.clearPolling()
      this.includeUsedDirectoryCandidates = false
      this.error = ''
      this.sourceError = ''
      const revision = this.requestRevision
      const result = await bridge.start_cover_wizard({ includeExisting })
      if (revision !== this.requestRevision) return false
      if (!result.ok) return this.fail(result.error.message)
      this.session = result.data
      this.selectedGameId = result.data.currentGameId
      this.selectedCandidateId = null
      this.candidates = []
      if (this.selectedGameId) await this.loadCandidates(bridge, this.selectedGameId)
      return true
    },
    async refresh(bridge: GameSaveScoutBridge) {
      if (!this.session) return
      const sessionId = this.session.id
      const revision = this.requestRevision
      const result = await bridge.cover_wizard_snapshot({ sessionId })
      if (revision !== this.requestRevision || this.session?.id !== sessionId) return
      if (!result.ok) return this.fail(result.error.message)
      this.session = result.data
      if (this.selectedGameId) await this.loadCandidates(bridge, this.selectedGameId)
    },
    async selectGame(bridge: GameSaveScoutBridge, gameId: string | null) {
      this.requestRevision += 1
      this.selectedGameId = gameId
      this.selectedCandidateId = null
      this.candidates = []
      this.error = ''
      if (gameId) await this.loadCandidates(bridge, gameId)
    },
    async loadCandidates(bridge: GameSaveScoutBridge, gameId: string) {
      if (!this.session) return
      const sessionId = this.session.id
      const revision = this.requestRevision
      const result = await bridge.list_cover_candidates({
        sessionId,
        gameId,
        includeUsed: this.includeUsedDirectoryCandidates,
      })
      if (
        revision !== this.requestRevision
        || this.session?.id !== sessionId
        || this.selectedGameId !== gameId
      ) return
      if (!result.ok) return this.fail(result.error.message)
      this.candidates = result.data
      if (!result.data.some((item) => item.id === this.selectedCandidateId)) {
        this.selectedCandidateId = null
      }
    },
    async setIncludeUsedDirectoryCandidates(
      bridge: GameSaveScoutBridge,
      includeUsed: boolean,
    ) {
      this.includeUsedDirectoryCandidates = includeUsed
      this.selectedCandidateId = null
      if (this.selectedGameId) {
        await this.loadCandidates(bridge, this.selectedGameId)
      }
    },
    async setIncludeExisting(bridge: GameSaveScoutBridge, includeExisting: boolean) {
      if (!this.session) return false
      const sessionId = this.session.id
      const result = await bridge.set_cover_wizard_include_existing({
        sessionId,
        includeExisting,
      })
      if (!result.ok) return this.fail(result.error.message)
      if (this.session?.id !== sessionId) return false
      this.session = result.data
      if (!result.data.queue.some((item) => item.gameId === this.selectedGameId)) {
        await this.selectGame(bridge, result.data.currentGameId)
      }
      return true
    },
    async addUploads(
      bridge: GameSaveScoutBridge,
      uploads: CoverUpload[],
      source: 'clipboard' | 'drop',
    ) {
      if (!this.session || !this.selectedGameId) return false
      this.sourceError = ''
      const sessionId = this.session.id
      const gameId = this.selectedGameId
      for (const upload of uploads) {
        const result = await bridge.add_cover_candidate_bytes({
          sessionId,
          gameId,
          source,
          ...upload,
        })
        if (this.session?.id !== sessionId || this.selectedGameId !== gameId) return false
        if (!result.ok) {
          this.sourceError = result.error.message
          return false
        }
      }
      await this.refresh(bridge)
      return true
    },
    async startSourceTask(
      bridge: GameSaveScoutBridge,
      pending: Promise<SourceTaskResult>,
    ) {
      this.sourceError = ''
      const result = await pending
      if (!result.ok) {
        this.sourceError = result.error.message
        return false
      }
      this.pollRevision += 1
      const pollRevision = this.pollRevision
      this.activeTaskId = result.data.taskId
      this.taskSnapshot = null
      await this.pollTask(bridge, result.data.taskId, pollRevision)
      return true
    },
    async pollTask(bridge: GameSaveScoutBridge, taskId: string, pollRevision: number) {
      const result = await bridge.task_snapshot(taskId)
      if (pollRevision !== this.pollRevision || this.activeTaskId !== taskId) return
      if (!result.ok) {
        this.sourceError = result.error.message
        this.activeTaskId = null
        return
      }
      this.taskSnapshot = result.data
      if (activeTaskStatuses.has(result.data.status)) {
        this.pollTimer = window.setTimeout(
          () => void this.pollTask(bridge, taskId, pollRevision),
          POLL_INTERVAL_MS,
        )
        return
      }
      this.pollTimer = null
      this.activeTaskId = null
      if (result.data.status === 'failed') {
        this.sourceError = result.data.error?.message ?? '封面来源收集失败。'
      }
      await this.refresh(bridge)
    },
    async adopt(bridge: GameSaveScoutBridge): Promise<Game | null> {
      if (!this.session || !this.selectedGameId || !this.selectedCandidateId) return null
      const sessionId = this.session.id
      const gameId = this.selectedGameId
      const candidateId = this.selectedCandidateId
      const result = await bridge.adopt_cover_candidate({
        sessionId,
        gameId,
        candidateId,
      })
      if (
        this.session?.id !== sessionId
        || this.selectedGameId !== gameId
        || this.selectedCandidateId !== candidateId
      ) return result.ok ? result.data.game : null
      if (!result.ok) {
        this.error = result.error.message
        return null
      }
      this.session = result.data.snapshot
      this.selectedCandidateId = null
      this.candidates = []
      await this.selectGame(bridge, result.data.snapshot.currentGameId)
      return result.data.game
    },
    async skip(bridge: GameSaveScoutBridge) {
      if (!this.session || !this.selectedGameId) return false
      const result = await bridge.skip_cover_wizard_game({
        sessionId: this.session.id,
        gameId: this.selectedGameId,
      })
      if (!result.ok) return this.fail(result.error.message)
      this.session = result.data
      await this.selectGame(bridge, result.data.currentGameId)
      return true
    },
    async requestClose(bridge: GameSaveScoutBridge) {
      if (!this.session || this.closing) return false
      this.closing = true
      const sessionId = this.session.id
      try {
        if (this.activeTaskId) {
          const taskId = this.activeTaskId
          await bridge.cancel_task(taskId)
          await this.waitForTaskTerminal(bridge, taskId)
        }
        return await this.close(bridge, sessionId)
      } finally {
        this.closing = false
      }
    },
    async waitForTaskTerminal(bridge: GameSaveScoutBridge, taskId: string) {
      for (;;) {
        const result = await bridge.task_snapshot(taskId)
        if (!result.ok || !activeTaskStatuses.has(result.data.status)) return
        await new Promise<void>((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS))
      }
    },
    async close(
      bridge: GameSaveScoutBridge,
      sessionId?: string,
    ): Promise<boolean> {
      const targetSessionId = sessionId ?? this.session?.id
      if (!targetSessionId) return true
      let result = await bridge.close_cover_wizard({ sessionId: targetSessionId })
      if (!result.ok && result.error.code === 'cover_wizard_busy' && this.activeTaskId) {
        await this.waitForTaskTerminal(bridge, this.activeTaskId)
        result = await bridge.close_cover_wizard({ sessionId: targetSessionId })
      }
      if (!result.ok) {
        return this.fail(result.error.message)
      }
      this.clearPolling()
      this.session = null
      this.candidates = []
      this.selectedGameId = null
      this.selectedCandidateId = null
      this.activeTaskId = null
      this.taskSnapshot = null
      this.error = ''
      this.sourceError = ''
      this.includeUsedDirectoryCandidates = false
      return true
    },
    fail(message: string) {
      this.error = message
      return false
    },
  },
})
