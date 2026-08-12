<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { GameShelfBridge, LudusaviStatus } from '../../api/contracts'

const props = defineProps<{ bridge: GameShelfBridge }>()

const status = ref<LudusaviStatus | null>(null)
const loading = ref(false)
const message = ref('')
let pollTimer: number | undefined

onMounted(() => void loadStatus())
onBeforeUnmount(() => {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
})

async function loadStatus() {
  loading.value = true
  const result = await props.bridge.ludusavi_status()
  loading.value = false
  if (!result.ok) return void (message.value = result.error.message)
  status.value = result.data
}

async function updateManifest() {
  loading.value = true
  message.value = '正在启动清单更新任务……'
  const result = await props.bridge.update_ludusavi({})
  loading.value = false
  if (!result.ok) return void (message.value = result.error.message)
  message.value = '清单更新任务已启动。'
  await pollTask(result.data.taskId)
}

async function pollTask(taskId: string) {
  const result = await props.bridge.task_snapshot(taskId)
  if (!result.ok) return void (message.value = result.error.message)
  const task = result.data
  if (task.status === 'completed') {
    message.value = 'Ludusavi 清单已检查完成。'
    await loadStatus()
    return
  }
  if (task.status === 'failed' || task.status === 'cancelled') {
    message.value = task.error?.message ?? '清单更新没有完成。'
    return
  }
  message.value = task.message || '正在更新 Ludusavi 清单……'
  pollTimer = window.setTimeout(() => void pollTask(taskId), 350)
}

async function openCustomDirectory() {
  const result = await props.bridge.open_custom_manifest_directory()
  if (!result.ok) message.value = result.error.message
}
</script>

<template>
  <section class="ludusavi-settings">
    <h4>Ludusavi 存档规则</h4>
    <p>程序使用随包附带或由你手动更新的规则清单；启动时不会联网更新。</p>
    <dl v-if="status" class="manifest-metadata">
      <dt>清单来源</dt><dd>{{ status.sourceUrl }}</dd>
      <dt>获取时间</dt><dd>{{ new Date(status.downloadedAt).toLocaleString() }}</dd>
      <dt>SHA-256</dt><dd><code>{{ status.sha256.slice(0, 12) }}</code></dd>
      <dt>ETag</dt><dd>{{ status.etag ?? '无' }}</dd>
      <dt>自定义清单目录</dt><dd>{{ status.customDirectory }}</dd>
    </dl>
    <ul v-if="status?.customErrors.length" class="manifest-errors">
      <li v-for="error in status.customErrors" :key="`${error.sourceName}:${error.message}`">
        {{ error.sourceName }}：{{ error.message }}
      </li>
    </ul>
    <div class="compact-actions">
      <button data-test="update-ludusavi" type="button" :disabled="loading" @click="updateManifest">
        检查并更新清单
      </button>
      <button data-test="open-custom-manifests" type="button" class="secondary" @click="openCustomDirectory">
        打开自定义清单目录
      </button>
    </div>
    <p class="status-message" aria-live="polite">{{ loading ? '正在读取清单状态……' : message }}</p>
  </section>
</template>
