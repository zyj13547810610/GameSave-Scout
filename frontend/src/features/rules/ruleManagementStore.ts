import { defineStore } from 'pinia'
import type {
  GameSaveScoutBridge,
  RuleDetail,
  RuleDiagnostic,
  RuleDraft,
  RuleDraftValidation,
  RuleImportDecision,
  RuleImportPreview,
  RuleSource,
  RuleStatus,
  RuleSummary,
  RuleTestResult,
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

function verificationMaterial(draft: RuleDraft): string {
  if (draft.type === 'engine') {
    return JSON.stringify({
      id: draft.id, type: draft.type, variant: draft.variant ?? null,
      threshold: draft.threshold, all: draft.all, any: draft.any, negative: draft.negative,
    })
  }
  if (draft.type === 'save_game') {
    return JSON.stringify({
      id: draft.id, type: draft.type, titles: draft.titles,
      product_ids: draft.product_ids, locations: draft.locations,
    })
  }
  return JSON.stringify({
    id: draft.id, type: draft.type, engine_ids: draft.engine_ids, locations: draft.locations,
  })
}

function cloneDraft(draft: RuleDraft): RuleDraft {
  return JSON.parse(JSON.stringify(draft)) as RuleDraft
}

function gameRuleId(gameId: string): string {
  const normalized = gameId.toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '')
  return `game_${normalized || 'save'}`.slice(0, 80)
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
    validation: null as RuleDraftValidation | null,
    testResult: null as RuleTestResult | null,
    verificationToken: null as string | null,
    verifiedMaterial: null as string | null,
    dirty: false,
    editing: false,
    mobilePane: 'list' as 'list' | 'detail',
    focusQualifiedId: null as string | null,
    diagnostics: [] as RuleDiagnostic[],
    catalogVersion: '',
    generation: 0,
    initialized: false,
    listLoading: false,
    detailLoading: false,
    refreshing: false,
    validating: false,
    testing: false,
    mutating: false,
    importing: false,
    prefilling: false,
    listError: '',
    detailError: '',
    refreshError: '',
    mutationError: '',
    notice: '',
    importPreview: null as RuleImportPreview | null,
    importError: '',
    prefillError: '',
    listRequestSequence: 0,
    detailRequestSequence: 0,
    validationRequestSequence: 0,
    queryTimer: null as number | null,
  }),
  getters: {
    canMarkVerified: (state) => Boolean(
      state.draft
      && state.verificationToken
      && state.verifiedMaterial === verificationMaterial(state.draft),
    ),
  },
  actions: {
    async ensureLoaded(bridge: GameSaveScoutBridge) {
      if (this.initialized) return
      await this.loadList(bridge)
    },
    async loadList(bridge: GameSaveScoutBridge) {
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
    setQuery(bridge: GameSaveScoutBridge, query: string) {
      this.filters.query = query
      this.filters.offset = 0
      if (this.queryTimer !== null) window.clearTimeout(this.queryTimer)
      this.queryTimer = window.setTimeout(() => {
        this.queryTimer = null
        void this.loadList(bridge)
      }, 300)
    },
    async setFilter<K extends EnumFilterKey>(
      bridge: GameSaveScoutBridge,
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
    async setTab(bridge: GameSaveScoutBridge, tab: RuleManagementTab) {
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
    async openIntent(
      bridge: GameSaveScoutBridge,
      intent: { tab: RuleManagementTab; gameId?: string },
    ) {
      this.prefillError = ''
      await this.setTab(bridge, intent.tab)
      if (intent.tab !== 'save' || !intent.gameId) return
      this.prefilling = true
      const result = await bridge.get_game_save_rule_prefill({ gameId: intent.gameId })
      this.prefilling = false
      if (!result.ok) {
        this.prefillError = result.error.message
        return
      }
      const prefill = result.data
      const titles = [...new Set([prefill.title, ...prefill.aliases].map((item) => item.trim()).filter(Boolean))]
      const draft: RuleDraft = {
        version: '1',
        id: gameRuleId(prefill.gameId),
        label: `${prefill.title} 存档`,
        type: 'save_game',
        status: 'experimental',
        priority: 100,
        enabled: true,
        notes: null,
        references: [],
        titles,
        product_ids: [...prefill.productIds],
        locations: prefill.locations.map((location) => ({
          kind: location.kind,
          path: location.pathTemplate,
          category: location.category,
          confidence: location.confidence,
          require_existing: false,
        })),
      }
      this.startNew('save_game')
      this.draft = draft
      this.dirty = true
      await this.validateDraft(bridge, draft)
    },
    async selectRule(bridge: GameSaveScoutBridge, qualifiedId: string) {
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
      this.focusQualifiedId = null
      this.detail = result.data
      this.draft = null
      this.validation = null
      this.testResult = null
      this.verificationToken = null
      this.verifiedMaterial = null
      this.dirty = false
      this.editing = false
      this.mobilePane = 'detail'
    },
    startNew(type: RuleType) {
      this.selectedQualifiedId = null
      this.detail = null
      this.draft = defaultDraft(type)
      this.validation = null
      this.testResult = null
      this.verificationToken = null
      this.verifiedMaterial = null
      this.dirty = false
      this.editing = true
      this.mobilePane = 'detail'
    },
    startEdit() {
      if (!this.detail?.capabilities.edit) return
      this.draft = cloneDraft(this.detail.draft)
      this.validation = {
        valid: true,
        normalizedDraft: cloneDraft(this.detail.draft),
        yamlPreview: this.detail.yamlPreview,
        errorCode: null,
        message: '规则草稿有效。',
      }
      this.testResult = null
      this.verificationToken = null
      this.verifiedMaterial = null
      this.dirty = false
      this.editing = true
      this.mobilePane = 'detail'
    },
    backToList() {
      this.mobilePane = 'list'
    },
    discardDraft() {
      this.draft = null
      this.validation = null
      this.testResult = null
      this.verificationToken = null
      this.verifiedMaterial = null
      this.dirty = false
      this.editing = false
    },
    updateDraft(draft: RuleDraft) {
      this.validationRequestSequence += 1
      this.validating = false
      if (
        this.verificationToken
        && this.verifiedMaterial
        && verificationMaterial(draft) !== this.verifiedMaterial
      ) {
        this.verificationToken = null
        if (draft.status === 'formal') draft = { ...draft, status: 'experimental' } as RuleDraft
      }
      this.draft = draft
      this.validation = null
      this.dirty = true
      this.mutationError = ''
      this.notice = ''
    },
    async validateDraft(bridge: GameSaveScoutBridge, draft: RuleDraft) {
      const requestId = ++this.validationRequestSequence
      this.validating = true
      const result = await bridge.validate_rule_draft({ draft })
      if (requestId !== this.validationRequestSequence) return
      this.validating = false
      if (!result.ok) {
        this.validation = {
          valid: false, normalizedDraft: null, yamlPreview: null,
          errorCode: result.error.code, message: result.error.message,
        }
        return
      }
      this.validation = result.data
    },
    async testDraft(bridge: GameSaveScoutBridge, gameId: string) {
      const sourceDraft = this.draft ?? this.detail?.draft
      if (!sourceDraft || this.testing) return
      this.testing = true
      this.mutationError = ''
      const testedDraft = cloneDraft(sourceDraft)
      const result = await bridge.test_rule_draft({ draft: testedDraft, gameId })
      this.testing = false
      if (!result.ok) {
        this.mutationError = result.error.message
        return
      }
      this.testResult = result.data
      const testedMaterial = verificationMaterial(testedDraft)
      const stillCurrent = this.draft && verificationMaterial(this.draft) === testedMaterial
      this.verificationToken = stillCurrent ? result.data.verificationToken : null
      this.verifiedMaterial = this.verificationToken ? testedMaterial : null
    },
    markVerified() {
      if (
        !this.draft
        || !this.verificationToken
        || this.verifiedMaterial !== verificationMaterial(this.draft)
      ) return
      this.draft = { ...this.draft, status: 'formal' } as RuleDraft
      this.validation = null
      this.dirty = true
    },
    async saveDraft(bridge: GameSaveScoutBridge) {
      if (!this.draft || !this.validation?.valid || this.mutating) return
      this.mutating = true
      this.mutationError = ''
      this.notice = ''
      const result = await bridge.save_rule({
        originalQualifiedId: this.editing && this.detail ? this.detail.qualifiedId : null,
        draft: this.validation.normalizedDraft ?? this.draft,
        verificationToken: this.verificationToken,
      })
      this.mutating = false
      if (!result.ok) {
        this.mutationError = result.error.message
        return
      }
      this.applySavedDetail(result.data.detail, result.data.generation)
      this.notice = '规则已保存；变更只影响下一次识别或查找任务。'
    },
    async copyRule(bridge: GameSaveScoutBridge, qualifiedId: string) {
      if (this.mutating) return
      this.mutating = true
      this.mutationError = ''
      const result = await bridge.copy_rule({ qualifiedId })
      this.mutating = false
      if (!result.ok) {
        this.mutationError = result.error.message
        return
      }
      this.applySavedDetail(result.data.detail, result.data.generation)
      this.notice = '已复制为新的用户实验规则。'
    },
    async toggleRule(bridge: GameSaveScoutBridge, detail: RuleDetail) {
      if (this.mutating) return
      this.mutating = true
      this.mutationError = ''
      const result = await bridge.set_rule_enabled({
        qualifiedId: detail.qualifiedId,
        enabled: !detail.enabled,
      })
      this.mutating = false
      if (!result.ok) {
        this.mutationError = result.error.message
        return
      }
      this.applySavedDetail(result.data.detail, result.data.generation)
      this.notice = `规则已${result.data.detail.enabled ? '启用' : '停用'}；只影响下一次任务。`
    },
    async deleteRule(bridge: GameSaveScoutBridge, qualifiedId: string) {
      if (this.mutating) return
      const index = this.items.findIndex((item) => item.qualifiedId === qualifiedId)
      this.mutating = true
      this.mutationError = ''
      const result = await bridge.delete_rule({ qualifiedId })
      this.mutating = false
      if (!result.ok) {
        this.mutationError = result.error.message
        return
      }
      this.items = this.items.filter((item) => item.qualifiedId !== qualifiedId)
      this.total = Math.max(0, this.total - 1)
      this.generation = result.data.generation
      this.selectedQualifiedId = null
      this.detail = null
      this.discardDraft()
      this.mobilePane = 'list'
      this.notice = '用户规则已删除；只影响下一次任务。'
      const neighbor = this.items[Math.min(Math.max(index, 0), this.items.length - 1)]
      if (neighbor) {
        await this.selectRule(bridge, neighbor.qualifiedId)
        this.mobilePane = 'list'
        this.focusQualifiedId = neighbor.qualifiedId
      }
    },
    clearFocusRequest() {
      this.focusQualifiedId = null
    },
    async exportRule(bridge: GameSaveScoutBridge, qualifiedId: string) {
      if (this.mutating) return
      this.mutating = true
      this.mutationError = ''
      const result = await bridge.export_rule({ qualifiedId })
      this.mutating = false
      if (!result.ok) {
        this.mutationError = result.error.message
        return
      }
      this.notice = result.data.cancelled
        ? '已取消导出，规则没有改变。'
        : `规则已导出为 ${result.data.fileName ?? 'YAML 文件'}。`
    },
    async beginImport(bridge: GameSaveScoutBridge) {
      if (this.importing) return
      this.importing = true
      this.importError = ''
      this.notice = ''
      const result = await bridge.begin_rule_import({})
      this.importing = false
      if (!result.ok) {
        this.importError = result.error.message
        return
      }
      if (result.data.cancelled) {
        this.notice = '已取消导入。'
        return
      }
      this.importPreview = result.data
    },
    closeImport() {
      if (this.importing) return
      this.importPreview = null
      this.importError = ''
    },
    async confirmImport(bridge: GameSaveScoutBridge, decisions: RuleImportDecision[]) {
      if (!this.importPreview || this.importing) return
      this.importing = true
      this.importError = ''
      const result = await bridge.confirm_rule_import({
        sessionId: this.importPreview.sessionId,
        decisions,
      })
      this.importing = false
      if (!result.ok) {
        this.importError = result.error.message
        return
      }
      const firstImported = result.data.importedQualifiedIds[0] ?? null
      this.importPreview = null
      this.generation = result.data.generation
      this.notice = `已导入 ${result.data.importedQualifiedIds.length} 条规则，跳过 ${result.data.skippedCount} 条。`
      await this.loadList(bridge)
      if (firstImported) await this.selectRule(bridge, firstImported)
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
      this.validation = null
      this.testResult = null
      this.verificationToken = null
      this.verifiedMaterial = null
      this.dirty = false
      this.editing = false
      this.generation = generation
    },
    async refreshRules(bridge: GameSaveScoutBridge) {
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
