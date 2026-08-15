<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { GuidedSessionStatus } from '../../api/contracts'
import { useGuidedSaveStore } from './guidedSaveStore'

const emit = defineEmits<{ restore: [gameId: string] }>()
const store = useGuidedSaveStore()
const { session } = storeToRefs(store)
const now = ref(Date.now())
let clock: number | null = null
const active = computed(() => session.value && ['preparing', 'monitoring', 'settling'].includes(session.value.status))
const statusLabels: Partial<Record<GuidedSessionStatus, string>> = {
  preparing: '正在准备',
  monitoring: '监控中',
  settling: '正在等待写盘并分析',
}
const statusLabel = computed(() => session.value ? (statusLabels[session.value.status] ?? '') : '')
const elapsed = computed(() => {
  if (!session.value) return ''
  const started = Date.parse(session.value.monitoringStartedAt ?? session.value.startedAt)
  const seconds = Math.max(0, Math.floor((now.value - started) / 1000))
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`
})

onMounted(() => { clock = window.setInterval(() => { now.value = Date.now() }, 1000) })
onBeforeUnmount(() => { if (clock !== null) window.clearInterval(clock) })
</script>

<template>
  <section v-if="active && session" data-test="guided-save-status-bar" class="guided-save-status-bar" role="status">
    <div>
      <strong>正在为《{{ session.gameTitle }}》寻找存档</strong>
      <span>{{ statusLabel }} · {{ elapsed }}</span>
    </div>
    <button data-test="restore-guided-save" type="button" @click="emit('restore', session.gameId)">返回向导</button>
  </section>
</template>
