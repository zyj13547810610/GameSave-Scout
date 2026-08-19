<script setup lang="ts">
import { computed } from 'vue'
import type { BatchSaveScanSummary, TaskSnapshot } from '../../api/contracts'

const props = defineProps<{ task: TaskSnapshot | null; busy: boolean }>()
defineEmits<{ cancel: [] }>()

const active = computed(() => props.task && ['queued', 'running'].includes(props.task.status))
const details = computed(() => props.task?.details ?? {})
const summary = computed(() => (
  props.task?.status === 'completed' || props.task?.status === 'cancelled'
    ? props.task.result as BatchSaveScanSummary | null
    : null
))
const completed = computed(() => props.task?.progress.completed ?? 0)
const total = computed(() => props.task?.progress.total)
const detailValue = (...keys: string[]) => {
  for (const key of keys) {
    const value = details.value[key]
    if (value !== undefined && value !== null && value !== '') return value
  }
  return null
}
</script>

<template>
  <section class="batch-save-progress" data-test="batch-save-progress" aria-live="polite">
    <div class="batch-progress-heading">
      <div>
        <strong>{{ task?.message || '尚未开始扫描' }}</strong>
        <span v-if="active">{{ completed }} / {{ total ?? '—' }}</span>
      </div>
      <button v-if="active" data-test="cancel-batch-scan" type="button" class="secondary" :disabled="busy" @click="$emit('cancel')">取消扫描</button>
    </div>
    <progress v-if="active" :value="completed" :max="total ?? Math.max(1, completed + 1)" />
    <dl v-if="active && Object.keys(details).length" class="batch-progress-details">
      <template v-if="detailValue('currentScope', 'scope')"><dt>范围</dt><dd>{{ detailValue('currentScope', 'scope') }}</dd></template>
      <template v-if="detailValue('currentDirectory', 'currentPath')"><dt>当前目录</dt><dd>{{ detailValue('currentDirectory', 'currentPath') }}</dd></template>
      <template v-if="detailValue('entriesVisited', 'entries') !== null"><dt>已访问条目</dt><dd>{{ detailValue('entriesVisited', 'entries') }}</dd></template>
      <template v-if="detailValue('candidateCount') !== null"><dt>候选</dt><dd>{{ detailValue('candidateCount') }}</dd></template>
      <template v-if="detailValue('elapsedSeconds') !== null"><dt>耗时</dt><dd>{{ detailValue('elapsedSeconds') }} 秒</dd></template>
    </dl>
    <div v-if="summary" class="batch-scan-summary">
      <span>新发现 {{ summary.newCount }}</span><span>待处理 {{ summary.pendingCount }}</span>
      <span>已记录 {{ summary.recordedCount }}</span><span>已忽略 {{ summary.ignoredCount }}</span>
      <span>不可用 {{ summary.unavailableCount }}</span><span>自动归组 {{ summary.groupCount }}</span>
      <span>不可访问范围 {{ summary.inaccessibleScopeCount }}</span><span>截断范围 {{ summary.truncatedScopeCount }}</span>
      <span>总耗时 {{ summary.elapsedSeconds }} 秒</span>
    </div>
  </section>
</template>
