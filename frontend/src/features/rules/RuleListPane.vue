<script setup lang="ts">
import type { RuleSummary } from '../../api/contracts'

defineProps<{
  items: RuleSummary[]
  selectedQualifiedId: string | null
  loading: boolean
}>()

defineEmits<{ select: [qualifiedId: string] }>()

function sourceLabel(item: RuleSummary) {
  return item.source === 'builtin' ? '内置规则' : '用户规则'
}

function statusLabel(item: RuleSummary) {
  if (item.status === 'experimental') return '实验'
  return item.source === 'user' ? '已验证' : '正式'
}

function typeLabel(item: RuleSummary) {
  if (item.ruleType === 'engine') return '引擎识别'
  if (item.ruleType === 'save_engine') return '引擎存档'
  return '游戏存档'
}
</script>

<template>
  <section class="rule-list-pane" aria-label="规则列表">
    <div class="rule-pane-heading">
      <h3>规则目录</h3>
      <span>{{ items.length }} 条</span>
    </div>
    <div data-test="rule-list-scroll" class="rule-list-scroll" tabindex="0">
      <p v-if="loading && items.length === 0" class="rule-pane-message">正在读取规则…</p>
      <p v-else-if="items.length === 0" class="rule-pane-message">没有符合条件的规则。</p>
      <button
        v-for="item in items"
        :key="item.qualifiedId"
        type="button"
        class="rule-list-item"
        :class="{ selected: item.qualifiedId === selectedQualifiedId }"
        :aria-current="item.qualifiedId === selectedQualifiedId ? 'true' : undefined"
        @click="$emit('select', item.qualifiedId)"
      >
        <strong class="rule-list-label">{{ item.label }}</strong>
        <code>{{ item.qualifiedId }}</code>
        <span class="rule-list-badges">
          <span>{{ sourceLabel(item) }}</span>
          <span>{{ statusLabel(item) }}</span>
          <span>{{ typeLabel(item) }}</span>
          <span :class="{ disabled: !item.enabled }">{{ item.enabled ? '已启用' : '已停用' }}</span>
        </span>
      </button>
    </div>
  </section>
</template>
