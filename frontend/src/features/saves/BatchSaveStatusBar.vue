<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { computed } from 'vue'
import { useBatchSaveStore } from './batchSaveStore'

const emit = defineEmits<{ restore: [] }>()
const store = useBatchSaveStore()
const { task } = storeToRefs(store)
const active = computed(() => task.value && ['queued', 'running'].includes(task.value.status))
</script>

<template>
  <section v-if="active && task" class="batch-save-status-bar" data-test="batch-save-status-bar" role="status">
    <div>
      <strong>批量存档扫描正在运行</strong>
      <span>{{ task.message || '正在准备扫描范围' }}</span>
    </div>
    <button data-test="restore-batch-save" type="button" @click="emit('restore')">返回存档发现</button>
  </section>
</template>
