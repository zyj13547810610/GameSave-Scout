<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { onBeforeUnmount, onMounted } from 'vue'
import type { GameShelfBridge } from '../../api/contracts'
import { useBatchSaveStore } from './batchSaveStore'

const props = defineProps<{ bridge: GameShelfBridge }>()
const store = useBatchSaveStore()
const { task, total, loading, error, notice } = storeToRefs(store)

onMounted(() => void store.open(props.bridge))
onBeforeUnmount(() => store.clearPolling())
</script>

<template>
  <section class="batch-save-workspace" data-test="batch-save-workspace" aria-labelledby="batch-save-title">
    <header class="batch-save-heading">
      <div>
        <p>存档工具</p>
        <h1 id="batch-save-title">批量存档发现</h1>
      </div>
      <span v-if="task && (task.status === 'queued' || task.status === 'running')" class="batch-save-active-badge">扫描中</span>
    </header>
    <div class="batch-save-placeholder">
      <strong v-if="loading">正在加载候选…</strong>
      <strong v-else>已记录 {{ total }} 个候选</strong>
      <p>扫描范围、进度和候选审核将在这里集中管理。</p>
      <p v-if="task?.message" role="status">{{ task.message }}</p>
      <p v-if="notice" class="batch-save-notice" role="status">{{ notice }}</p>
      <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    </div>
  </section>
</template>
