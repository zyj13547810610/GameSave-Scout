<script setup lang="ts">
import type { CoverWizardQueueItem } from '../../api/contracts'

defineProps<{
  items: CoverWizardQueueItem[]
  selectedGameId: string | null
  includeExisting: boolean
}>()
defineEmits<{
  select: [gameId: string]
  'update:includeExisting': [value: boolean]
}>()

const statusLabels: Record<CoverWizardQueueItem['status'], string> = {
  pending: '待处理', ready: '已有候选', adopted: '已采用', skipped: '已跳过', failed: '失败',
}
</script>

<template>
  <aside class="cover-wizard-queue" aria-label="封面处理队列">
    <label class="cover-existing-toggle">
      <input
        type="checkbox"
        :checked="includeExisting"
        @change="$emit('update:includeExisting', ($event.target as HTMLInputElement).checked)"
      >
      包含已有封面
    </label>
    <select
      class="cover-queue-select"
      aria-label="当前游戏"
      :value="selectedGameId ?? ''"
      @change="$emit('select', ($event.target as HTMLSelectElement).value)"
    >
      <option v-for="item in items" :key="item.gameId" :value="item.gameId">
        {{ item.title }} · {{ statusLabels[item.status] }}
      </option>
    </select>
    <div class="cover-queue-list">
      <button
        v-for="item in items"
        :key="item.gameId"
        type="button"
        class="cover-queue-item"
        :class="{ selected: selectedGameId === item.gameId }"
        :aria-current="selectedGameId === item.gameId ? 'true' : undefined"
        @click="$emit('select', item.gameId)"
      >
        <span>{{ item.title }}</span>
        <small :class="`status-${item.status}`">
          {{ statusLabels[item.status] }}<template v-if="item.candidateCount"> · {{ item.candidateCount }}</template>
        </small>
      </button>
    </div>
  </aside>
</template>
