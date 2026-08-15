import { defineStore } from 'pinia'
import type {
  ApiResult,
  GameShelfBridge,
  GuidedSaveDiscovery,
  GuidedSaveSession,
} from '../../api/contracts'

const activeStatuses = new Set<GuidedSaveSession['status']>([
  'preparing',
  'monitoring',
  'settling',
])

export const useGuidedSaveStore = defineStore('guided-save', {
  state: () => ({
    session: null as GuidedSaveSession | null,
    discoveries: [] as GuidedSaveDiscovery[],
    error: '',
    pollTimer: null as number | null,
    pollRevision: 0,
    requestedGameId: null as string | null,
  }),
  actions: {
    clearPolling() {
      this.pollRevision += 1
      if (this.pollTimer !== null) window.clearTimeout(this.pollTimer)
      this.pollTimer = null
    },
    async refreshActive(bridge: GameShelfBridge) {
      this.clearPolling()
      this.error = ''
      const result = await bridge.current_guided_save_detection()
      if (!result.ok) return this.fail(result.error.message)
      this.session = result.data
      this.discoveries = []
      if (result.data === null) return
      if (activeStatuses.has(result.data.status)) {
        await this.startPolling(bridge, result.data.id)
      } else if (result.data.status === 'completed') {
        await this.loadDiscoveries(bridge, result.data.id)
      }
    },
    async refreshForGame(bridge: GameShelfBridge, gameId: string) {
      this.requestedGameId = gameId
      if (this.session && activeStatuses.has(this.session.status)) return
      this.clearPolling()
      this.error = ''
      const result = await bridge.latest_guided_save_detection_for_game({ gameId })
      if (!result.ok) return this.fail(result.error.message)
      this.session = result.data
      this.discoveries = []
      if (result.data?.status === 'completed') {
        await this.loadDiscoveries(bridge, result.data.id)
      }
    },
    async startPolling(bridge: GameShelfBridge, sessionId: string) {
      this.clearPolling()
      const revision = this.pollRevision
      await this.pollOnce(bridge, sessionId, revision)
    },
    async pollOnce(bridge: GameShelfBridge, sessionId: string, revision: number) {
      const result = await bridge.guided_save_detection_status({ sessionId })
      if (revision !== this.pollRevision) return
      if (!result.ok) return this.fail(result.error.message)
      this.session = result.data
      if (activeStatuses.has(result.data.status)) {
        this.pollTimer = window.setTimeout(
          () => void this.pollOnce(bridge, sessionId, revision),
          1000,
        )
        return
      }
      this.pollTimer = null
      if (result.data.status === 'completed') {
        await this.loadDiscoveries(bridge, sessionId)
      }
    },
    async loadDiscoveries(bridge: GameShelfBridge, sessionId: string) {
      const result = await bridge.list_guided_save_discoveries({ sessionId })
      if (!result.ok) return this.fail(result.error.message)
      this.discoveries = result.data.filter((item) => item.reviewStatus === 'unreviewed')
    },
    async start(
      bridge: GameShelfBridge,
      gameId: string,
      selectedScopeIds: string[],
      additionalDirectories: string[],
    ) {
      this.error = ''
      const result = await bridge.start_guided_save_detection({
        gameId,
        selectedScopeIds,
        additionalDirectories,
      })
      if (!result.ok) return this.fail(result.error.message)
      this.requestedGameId = gameId
      this.session = result.data
      this.discoveries = []
      await this.startPolling(bridge, result.data.id)
    },
    async markSaved(bridge: GameShelfBridge) {
      if (!this.session) return
      await this.applySessionCommand(
        bridge,
        bridge.mark_guided_save_saved({ sessionId: this.session.id }),
      )
    },
    async stopAndAnalyze(bridge: GameShelfBridge) {
      if (!this.session) return
      await this.applySessionCommand(
        bridge,
        bridge.stop_guided_save_detection({ sessionId: this.session.id }),
      )
    },
    async cancel(bridge: GameShelfBridge) {
      if (!this.session) return
      await this.applySessionCommand(
        bridge,
        bridge.cancel_guided_save_detection({ sessionId: this.session.id }),
      )
    },
    async applySessionCommand(
      bridge: GameShelfBridge,
      pending: Promise<ApiResult<GuidedSaveSession>>,
    ) {
      this.error = ''
      const result = await pending
      if (!result.ok) return this.fail(result.error.message)
      this.session = result.data
      if (activeStatuses.has(result.data.status)) {
        await this.startPolling(bridge, result.data.id)
      } else {
        this.clearPolling()
        if (result.data.status === 'completed') {
          await this.loadDiscoveries(bridge, result.data.id)
        }
      }
    },
    async accept(
      bridge: GameShelfBridge,
      discoveryIds: string[],
      confirmRegistry: boolean,
    ) {
      if (!this.session) return false
      this.error = ''
      const result = await bridge.accept_guided_save_discoveries({
        sessionId: this.session.id,
        discoveryIds,
        confirmRegistry,
      })
      if (!result.ok) {
        this.fail(result.error.message)
        return false
      }
      await this.loadDiscoveries(bridge, this.session.id)
      if (this.discoveries.length === 0) this.session = null
      return true
    },
    async discard(bridge: GameShelfBridge) {
      if (!this.session) return false
      this.error = ''
      const result = await bridge.discard_guided_save_detection({
        sessionId: this.session.id,
      })
      if (!result.ok) {
        this.fail(result.error.message)
        return false
      }
      this.clearPolling()
      this.session = null
      this.discoveries = []
      return true
    },
    async resolveClose(
      bridge: GameShelfBridge,
      resolution: 'return' | 'cancel_and_exit' | 'analyze_and_exit',
    ) {
      const result = await bridge.resolve_guided_close({ resolution })
      if (!result.ok) return this.fail(result.error.message)
      if (resolution === 'return' && this.session) {
        await this.startPolling(bridge, this.session.id)
      }
    },
    dismissError() { this.error = '' },
    fail(message: string) {
      this.clearPolling()
      this.error = message
    },
  },
})
