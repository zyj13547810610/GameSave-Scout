<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type {
  GameShelfBridge,
  LudusaviStatus,
  LudusaviUpdateResult,
} from '../../api/contracts'

const props = defineProps<{ bridge: GameShelfBridge }>()

const status = ref<LudusaviStatus | null>(null)
const statusLoading = ref(false)
const updating = ref(false)
const loading = computed(() => statusLoading.value || updating.value)
const message = ref('')
type ResultKind = LudusaviUpdateResult['status'] | null
const resultKind = ref<ResultKind>(null)
let pollTimer: number | undefined

onMounted(() => void loadStatus())
onBeforeUnmount(() => {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
})

async function loadStatus(options: { preserveMessage?: boolean } = {}) {
  statusLoading.value = true
  const result = await props.bridge.ludusavi_status()
  statusLoading.value = false
  if (!result.ok) {
    if (!options.preserveMessage) message.value = result.error.message
    return
  }
  status.value = result.data
}

async function updateManifest() {
  updating.value = true
  resultKind.value = null
  message.value = '正在启动清单更新任务……'
  const result = await props.bridge.update_ludusavi({})
  if (!result.ok) {
    updating.value = false
    resultKind.value = 'failed'
    return void (message.value = result.error.message)
  }
  message.value = '清单更新任务已启动。'
  await pollTask(result.data.taskId)
}

async function pollTask(taskId: string) {
  const result = await props.bridge.task_snapshot(taskId)
  if (!result.ok) {
    updating.value = false
    resultKind.value = 'failed'
    return void (message.value = result.error.message)
  }
  const task = result.data
  if (task.status === 'completed') {
    const updateResult = parseUpdateResult(task.result)
    resultKind.value = updateResult?.status ?? null
    message.value = updateResult?.message || task.message || 'Ludusavi 清单已检查完成。'
    updating.value = false
    await loadStatus({ preserveMessage: true })
    return
  }
  if (task.status === 'failed' || task.status === 'cancelled') {
    updating.value = false
    resultKind.value = 'failed'
    message.value = task.error?.message ?? '清单更新没有完成。'
    return
  }
  message.value = task.message || '正在更新 Ludusavi 清单……'
  pollTimer = window.setTimeout(() => void pollTask(taskId), 350)
}

function parseUpdateResult(value: unknown): LudusaviUpdateResult | null {
  if (typeof value !== 'object' || value === null) return null
  if (!('status' in value) || !('message' in value)) return null
  const allowed = ['updated', 'not_modified', 'invalid', 'failed'] as const
  if (!allowed.includes(value.status as typeof allowed[number])) return null
  if (typeof value.message !== 'string') return null
  return value as LudusaviUpdateResult
}
</script>

<template>
  <section class="ludusavi-settings">
    <h4>Ludusavi 存档规则</h4>
    <p>程序使用随包附带或由你手动更新的规则清单；启动时不会联网更新。</p>
    <dl v-if="status?.available && status.sha256 && status.downloadedAt" class="manifest-metadata">
      <dt>清单来源</dt><dd>{{ status.sourceUrl }}</dd>
      <dt>获取时间</dt><dd>{{ new Date(status.downloadedAt).toLocaleString() }}</dd>
      <dt>SHA-256</dt><dd><code>{{ status.sha256.slice(0, 12) }}</code></dd>
      <dt>ETag</dt><dd>{{ status.etag ?? '无' }}</dd>
    </dl>
    <p v-else-if="status && !status.available" class="manifest-unavailable">
      <strong>Ludusavi 官方规则暂不可用</strong><br>
      {{ status.unavailableReason ?? '未找到可用的官方清单。' }}
    </p>
    <div class="compact-actions">
      <button data-test="update-ludusavi" type="button" :disabled="loading" @click="updateManifest">
        检查并更新清单
      </button>
    </div>
    <p v-if="statusLoading" class="status-message" aria-live="polite">正在读取清单状态……</p>
    <p
      v-else-if="message"
      data-test="ludusavi-result"
      :class="['manifest-update-result', resultKind]"
      aria-live="polite"
    >
      {{ message }}
    </p>
  </section>
</template>
