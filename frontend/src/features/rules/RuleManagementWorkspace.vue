<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { onMounted } from 'vue'
import type { GameShelfBridge, RuleType } from '../../api/contracts'
import LudusaviSettings from '../saves/LudusaviSettings.vue'
import RuleDetailPane from './RuleDetailPane.vue'
import RuleDiagnosticsPanel from './RuleDiagnosticsPanel.vue'
import RuleListPane from './RuleListPane.vue'
import { useRuleManagementStore, type RuleManagementTab } from './ruleManagementStore'
import './rules.css'

const props = defineProps<{ bridge: GameShelfBridge }>()
const emit = defineEmits<{ leave: [] }>()
const store = useRuleManagementStore()
const {
  activeTab, filters, items, total, selectedQualifiedId, detail, draft, dirty,
  mobilePane, diagnostics, listLoading, detailLoading, refreshing,
  listError, detailError, refreshError,
} = storeToRefs(store)

onMounted(() => void store.ensureLoaded(props.bridge))

function changeTab(tab: RuleManagementTab) {
  void store.setTab(props.bridge, tab)
}

function setQuery(event: Event) {
  store.setQuery(props.bridge, (event.target as HTMLInputElement).value)
}

function setEnumFilter(event: Event, key: 'source' | 'status' | 'enabled') {
  void store.setFilter(props.bridge, key, (event.target as HTMLSelectElement).value as never)
}

function startNew() {
  const type: RuleType = activeTab.value === 'engine' ? 'engine' : 'save_game'
  store.startNew(type)
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
        <button class="secondary" type="button" :disabled="refreshing" @click="store.refreshRules(bridge)">
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
      <button type="button" @click="startNew">新建规则</button>
      <span class="rule-result-count">共 {{ total }} 条</span>
    </div>

    <p v-if="listError" class="inline-error rule-workspace-error" role="alert">{{ listError }}</p>
    <p v-if="refreshError" class="inline-error rule-workspace-error" role="alert">{{ refreshError }}</p>
    <RuleDiagnosticsPanel :bridge="bridge" :diagnostics="diagnostics" />

    <div
      v-if="activeTab !== 'ludusavi'"
      class="rule-workspace-body"
      :data-mobile-pane="mobilePane"
    >
      <RuleListPane
        :items="items"
        :selected-qualified-id="selectedQualifiedId"
        :loading="listLoading"
        @select="store.selectRule(bridge, $event)"
      />
      <RuleDetailPane
        :detail="detail"
        :draft="draft"
        :loading="detailLoading"
        :error="detailError"
        @back="store.backToList"
        @edit="store.startEdit"
      />
    </div>
    <div v-else data-test="ludusavi-settings" class="rule-ludusavi-scroll">
      <LudusaviSettings :bridge="bridge" />
    </div>
  </section>
</template>
