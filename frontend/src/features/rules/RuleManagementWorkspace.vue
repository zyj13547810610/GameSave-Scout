<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { nextTick, onMounted, ref } from 'vue'
import type { Game, GameShelfBridge, RuleImportDecision, RuleType } from '../../api/contracts'
import LudusaviSettings from '../saves/LudusaviSettings.vue'
import RuleDetailPane from './RuleDetailPane.vue'
import RuleDiagnosticsPanel from './RuleDiagnosticsPanel.vue'
import RuleListPane from './RuleListPane.vue'
import RuleImportDialog from './RuleImportDialog.vue'
import { useRuleManagementStore, type RuleManagementTab } from './ruleManagementStore'
import './rules.css'

const props = withDefaults(defineProps<{
  bridge: GameShelfBridge
  games?: Pick<Game, 'id' | 'title' | 'status'>[]
}>(), { games: () => [] })
const emit = defineEmits<{ leave: [] }>()
const store = useRuleManagementStore()
const {
  activeTab, filters, items, total, selectedQualifiedId, focusQualifiedId, detail, draft, dirty,
  mobilePane, diagnostics, listLoading, detailLoading, refreshing,
  validation, testResult, testing, mutating, importing, canMarkVerified,
  listError, detailError, refreshError, mutationError, notice, importPreview, importError,
} = storeToRefs(store)
const importButton = ref<HTMLButtonElement | null>(null)

onMounted(() => void store.ensureLoaded(props.bridge))

function changeTab(tab: RuleManagementTab) {
  if (!discardDirty()) return
  void store.setTab(props.bridge, tab)
}

function setQuery(event: Event) {
  store.setQuery(props.bridge, (event.target as HTMLInputElement).value)
}

function setEnumFilter(event: Event, key: 'source' | 'status' | 'enabled') {
  void store.setFilter(props.bridge, key, (event.target as HTMLSelectElement).value as never)
}

function startNew(type?: RuleType) {
  if (!discardDirty()) return
  type ??= activeTab.value === 'engine' ? 'engine' : 'save_game'
  store.startNew(type)
}

function selectRule(qualifiedId: string) {
  if (!discardDirty()) return
  void store.selectRule(props.bridge, qualifiedId)
}

function backToList() {
  if (!discardDirty()) return
  store.backToList()
}

function discardDirty() {
  if (!dirty.value) return true
  if (!window.confirm('当前规则草稿尚未保存，确认放弃这些修改吗？')) return false
  store.discardDraft()
  return true
}

function refreshRules() {
  if (!discardDirty()) return
  void store.refreshRules(props.bridge)
}

async function beginImport() {
  if (!discardDirty()) return
  await store.beginImport(props.bridge)
}

async function closeImport() {
  store.closeImport()
  await nextTick()
  importButton.value?.focus()
}

async function confirmImport(decisions: RuleImportDecision[]) {
  await store.confirmImport(props.bridge, decisions)
  if (!importPreview.value) await nextTick(() => importButton.value?.focus())
}

function requestLeave() {
  if (dirty.value && !window.confirm('当前规则草稿尚未保存，确认放弃并离开规则管理吗？')) return false
  store.discardDraft()
  emit('leave')
  return true
}

defineExpose({ requestLeave })
</script>

<template>
  <section data-test="rule-management-workspace" class="rule-management-workspace">
    <header class="rule-workspace-heading">
      <div><p>规则工具</p><h2>规则管理</h2></div>
      <div class="compact-actions">
        <button ref="importButton" class="secondary" type="button" :disabled="importing" @click="beginImport">
          {{ importing && !importPreview ? '正在选择…' : '导入规则' }}
        </button>
        <button class="secondary" type="button" :disabled="refreshing" @click="refreshRules">
          {{ refreshing ? '正在刷新…' : '刷新规则' }}
        </button>
        <button data-test="leave-rule-management" class="secondary" type="button" @click="requestLeave">返回游戏库</button>
      </div>
    </header>

    <div class="rule-tabs" role="tablist" aria-label="规则类型">
      <button data-test="rules-tab-engine" type="button" role="tab" :aria-selected="activeTab === 'engine'" @click="changeTab('engine')">引擎规则</button>
      <button data-test="rules-tab-save" type="button" role="tab" :aria-selected="activeTab === 'save'" @click="changeTab('save')">存档规则</button>
      <button data-test="rules-tab-ludusavi" type="button" role="tab" :aria-selected="activeTab === 'ludusavi'" @click="changeTab('ludusavi')">Ludusavi</button>
    </div>

    <div v-if="activeTab !== 'ludusavi'" data-test="rule-workspace-controls" class="rule-workspace-controls">
      <input type="search" aria-label="搜索规则" placeholder="搜索名称或规则 ID" :value="filters.query" @input="setQuery">
      <select aria-label="规则来源" :value="filters.source" @change="setEnumFilter($event, 'source')">
        <option value="all">全部来源</option><option value="builtin">内置规则</option><option value="user">用户规则</option>
      </select>
      <select aria-label="规则状态" :value="filters.status" @change="setEnumFilter($event, 'status')">
        <option value="all">全部状态</option><option value="formal">正式/已验证</option><option value="experimental">实验</option>
      </select>
      <select aria-label="启用状态" :value="filters.enabled" @change="setEnumFilter($event, 'enabled')">
        <option value="all">全部启用状态</option><option value="enabled">已启用</option><option value="disabled">已停用</option>
      </select>
      <button v-if="activeTab === 'engine'" type="button" @click="startNew('engine')">新建引擎规则</button>
      <div v-else class="compact-actions rule-new-save-actions">
        <button type="button" @click="startNew('save_game')">新建游戏专属</button>
        <button class="secondary" type="button" @click="startNew('save_engine')">新建引擎通用</button>
      </div>
      <span class="rule-result-count">共 {{ total }} 条</span>
    </div>

    <p v-if="listError" class="inline-error rule-workspace-error" role="alert">{{ listError }}</p>
    <p v-if="refreshError" class="inline-error rule-workspace-error" role="alert">{{ refreshError }}</p>
    <p v-if="importError && !importPreview" class="inline-error rule-workspace-error" role="alert">{{ importError }}</p>
    <p v-if="notice && !detail" class="rule-operation-notice rule-workspace-error" role="status">{{ notice }}</p>
    <RuleDiagnosticsPanel :bridge="bridge" :diagnostics="diagnostics" />

    <div
      v-if="activeTab !== 'ludusavi'"
      class="rule-workspace-body"
      :data-mobile-pane="mobilePane"
    >
      <RuleListPane
        :items="items"
        :selected-qualified-id="selectedQualifiedId"
        :focus-qualified-id="focusQualifiedId"
        :loading="listLoading"
        @select="selectRule"
        @focused="store.clearFocusRequest"
      />
      <RuleDetailPane
        :detail="detail"
        :draft="draft"
        :validation="validation"
        :test-result="testResult"
        :games="games"
        :loading="detailLoading"
        :busy="mutating"
        :testing="testing"
        :dirty="dirty"
        :can-mark-verified="canMarkVerified"
        :error="detailError"
        :mutation-error="mutationError"
        :notice="notice"
        @back="backToList"
        @edit="store.startEdit"
        @update-draft="store.updateDraft"
        @validate="store.validateDraft(bridge, $event)"
        @test="store.testDraft(bridge, $event)"
        @mark-verified="store.markVerified"
        @save="store.saveDraft(bridge)"
        @copy="store.copyRule(bridge, $event)"
        @toggle="store.toggleRule(bridge, $event)"
        @delete="store.deleteRule(bridge, $event)"
        @export="store.exportRule(bridge, $event)"
      />
    </div>
    <div v-else data-test="ludusavi-settings" class="rule-ludusavi-scroll">
      <LudusaviSettings :bridge="bridge" />
    </div>
    <RuleImportDialog
      v-if="importPreview"
      :preview="importPreview"
      :busy="importing"
      :error="importError"
      @confirm="confirmImport"
      @close="closeImport"
    />
  </section>
</template>
