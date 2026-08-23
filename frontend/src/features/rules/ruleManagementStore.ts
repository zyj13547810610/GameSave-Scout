import { defineStore } from 'pinia'
import type {
  GameShelfBridge,
  RuleDetail,
  RuleDiagnostic,
  RuleDraft,
  RuleSource,
  RuleStatus,
  RuleSummary,
  RuleType,
} from '../../api/contracts'

export type RuleManagementTab = 'engine' | 'save' | 'ludusavi'
export type RuleEnabledFilter = 'all' | 'enabled' | 'disabled'

type RuleFilters = {
  kind: 'all' | 'engine' | 'save'
  source: 'all' | RuleSource
  status: 'all' | RuleStatus
  enabled: RuleEnabledFilter
  query: string
  offset: number
  limit: number
}

type EnumFilterKey = 'source' | 'status' | 'enabled'

function defaultDraft(type: RuleType): RuleDraft {
  const common = {
    version: '1',
    id: '',
    label: '',
    status: 'experimental' as const,
    priority: 100,
    enabled: true,
    notes: null,
    references: [] as string[],
  }
  if (type === 'engine') {
    return { ...common, type, threshold: 1, all: [], any: [], negative: [] }
  }
  if (type === 'save_engine') {
    return { ...common, type, engine_ids: [], locations: [] }
  }
  return { ...common, type, titles: [], product_ids: [], locations: [] }
}

export const useRuleManagementStore = defineStore('rule-management', {
  state: () => ({
    activeTab: 'engine' as RuleManagementTab,
    filters: {
      kind: 'engine', source: 'all', status: 'all', enabled: 'all',
      query: '', offset: 0, limit: 100,
    } as RuleFilters,
    items: [] as RuleSummary[],
    total: 0,
    selectedQualifiedId: null as string | null,
    detail: null as RuleDetail | null,
    draft: null as RuleDraft | null,
    dirty: false,
    editing: false,
    mobilePane: 'list' as 'list' | 'detail',
    diagnostics: [] as RuleDiagnostic[],
    catalogVersion: '',
    generation: 0,
    initialized: false,
    listLoading: false,
    detailLoading: false,
    refreshing: false,
    listError: '',
    detailError: '',
    refreshError: '',
    listRequestSequence: 0,
    detailRequestSequence: 0,
    queryTimer: null as number | null,
  }),
  actions: {
    async ensureLoaded(bridge: GameShelfBridge) {
      if (this.initialized) return
      await this.loadList(bridge)
    },
    async loadList(bridge: GameShelfBridge) {
      const requestId = ++this.listRequestSequence
      this.listLoading = true
      this.listError = ''
      const result = await bridge.list_rules({ ...this.filters })
      if (requestId !== this.listRequestSequence) return
      this.listLoading = false
      this.initialized = true
      if (!result.ok) {
        this.listError = result.error.message
        return
      }
      this.items = result.data.items
      this.total = result.data.total
    },
    setQuery(bridge: GameShelfBridge, query: string) {
      this.filters.query = query
      this.filters.offset = 0
      if (this.queryTimer !== null) window.clearTimeout(this.queryTimer)
      this.queryTimer = window.setTimeout(() => {
        this.queryTimer = null
        void this.loadList(bridge)
      }, 300)
    },
    async setFilter<K extends EnumFilterKey>(
      bridge: GameShelfBridge,
      key: K,
      value: RuleFilters[K],
    ) {
      if (this.queryTimer !== null) {
        window.clearTimeout(this.queryTimer)
        this.queryTimer = null
      }
      this.filters[key] = value
      this.filters.offset = 0
      await this.loadList(bridge)
    },
    async setTab(bridge: GameShelfBridge, tab: RuleManagementTab) {
      if (this.queryTimer !== null) {
        window.clearTimeout(this.queryTimer)
        this.queryTimer = null
      }
      this.activeTab = tab
      if (tab === 'ludusavi') return
      this.filters.kind = tab
      this.filters.offset = 0
      await this.loadList(bridge)
    },
    async selectRule(bridge: GameShelfBridge, qualifiedId: string) {
      const requestId = ++this.detailRequestSequence
      this.detailLoading = true
      this.detailError = ''
      const result = await bridge.get_rule({ qualifiedId })
      if (requestId !== this.detailRequestSequence) return
      this.detailLoading = false
      if (!result.ok) {
        this.detailError = result.error.message
        return
      }
      this.selectedQualifiedId = qualifiedId
      this.detail = result.data
      this.draft = null
      this.dirty = false
      this.editing = false
      this.mobilePane = 'detail'
    },
    startNew(type: RuleType) {
      this.selectedQualifiedId = null
      this.detail = null
      this.draft = defaultDraft(type)
      this.dirty = false
      this.editing = true
      this.mobilePane = 'detail'
    },
    startEdit() {
      if (!this.detail?.capabilities.edit) return
      this.draft = structuredClone(this.detail.draft)
      this.dirty = false
      this.editing = true
      this.mobilePane = 'detail'
    },
    backToList() {
      this.mobilePane = 'list'
    },
    discardDraft() {
      this.draft = null
      this.dirty = false
      this.editing = false
    },
    applySavedDetail(detail: RuleDetail, generation: number) {
      const summary: RuleSummary = {
        qualifiedId: detail.qualifiedId,
        ruleId: detail.ruleId,
        label: detail.label,
        ruleType: detail.ruleType,
        source: detail.source,
        status: detail.status,
        enabled: detail.enabled,
        priority: detail.priority,
      }
      const index = this.items.findIndex((item) => item.qualifiedId === detail.qualifiedId)
      if (index >= 0) this.items.splice(index, 1, summary)
      else {
        this.items.unshift(summary)
        this.total += 1
      }
      this.selectedQualifiedId = detail.qualifiedId
      this.detail = detail
      this.draft = null
      this.dirty = false
      this.editing = false
      this.generation = generation
    },
    async refreshRules(bridge: GameShelfBridge) {
      this.refreshing = true
      this.refreshError = ''
      const result = await bridge.refresh_rules({})
      this.refreshing = false
      if (!result.ok) {
        this.refreshError = result.error.message
        return
      }
      this.diagnostics = result.data.diagnostics
      if (!result.data.applied) {
        this.refreshError = '规则刷新未应用，当前有效规则保持不变。'
        return
      }
      this.generation = result.data.generation
      this.catalogVersion = result.data.catalogVersion
      await this.loadList(bridge)
      if (this.selectedQualifiedId) {
        await this.selectRule(bridge, this.selectedQualifiedId)
      }
    },
  },
})
