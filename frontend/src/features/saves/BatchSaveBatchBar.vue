<script setup lang="ts">
import { computed } from 'vue'
import type { BatchSaveCandidate } from '../../api/contracts'

const props = defineProps<{ selected: BatchSaveCandidate[]; busy: boolean }>()
defineEmits<{
  accept: []
  associate: []
  saveOnly: []
  ignore: []
  restore: []
  clearUnavailable: []
  clearSelection: []
}>()
const kindCounts = computed(() => ({
  directory: props.selected.filter((item) => item.kind === 'directory').length,
  file: props.selected.filter((item) => item.kind === 'file').length,
  glob: props.selected.filter((item) => item.kind === 'glob').length,
  registry: props.selected.filter((item) => item.kind === 'registry').length,
}))
const gameCount = computed(() => new Set(
  props.selected
    .map((item) => item.reviewGameId ?? (item.confidence === 'high' ? item.suggestedGameId : null))
    .filter(Boolean),
).size)
const canAccept = computed(() => props.selected.some((item) => (
  item.reviewStatus === 'pending'
  && item.availability === 'available'
  && Boolean(item.reviewGameId || (item.confidence === 'high' && item.suggestedGameId))
)))
</script>

<template>
  <section v-if="selected.length" class="batch-save-batch-bar" data-test="batch-save-batch-bar">
    <p><strong>已选择 {{ selected.length }}</strong><span>涉及游戏 {{ gameCount }}</span><span>目录 {{ kindCounts.directory }}</span><span>文件 {{ kindCounts.file }}</span><span>通配符 {{ kindCounts.glob }}</span><span>注册表 {{ kindCounts.registry }}</span></p>
    <div>
      <button data-test="accept-selected-candidates" type="button" :disabled="busy || !canAccept" @click="$emit('accept')">添加所选</button>
      <button type="button" class="secondary" :disabled="busy" @click="$emit('associate')">调整关联</button>
      <button type="button" class="secondary" :disabled="busy" @click="$emit('saveOnly')">创建仅存档卡片</button>
      <button type="button" class="secondary" :disabled="busy" @click="$emit('ignore')">忽略</button>
      <button type="button" class="secondary" :disabled="busy" @click="$emit('restore')">恢复</button>
      <button type="button" class="danger" :disabled="busy" @click="$emit('clearUnavailable')">清除不可用历史</button>
      <button type="button" class="secondary" :disabled="busy" @click="$emit('clearSelection')">清除选择</button>
    </div>
  </section>
</template>
