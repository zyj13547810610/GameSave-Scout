<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { GameSaveScoutBridge, LudusaviStatus, LudusaviUpdateResult } from '../../api/contracts'

const props = defineProps<{ bridge: GameSaveScoutBridge }>()
const status = ref<LudusaviStatus | null>(null)
const loadingStatus = ref(false)
const updating = ref(false)
const restoring = ref(false)
const opening = ref(false)
const message = ref('')
const resultKind = ref<LudusaviUpdateResult['status'] | 'restored' | null>(null)
let pollTimer: number | null = null
const busy = computed(() => loadingStatus.value || updating.value || restoring.value || opening.value)
const sourceLabel = computed(() => {
  if (!status.value?.available) return '不可用'
  return status.value.source === 'active' ? '用户更新版本' : '随包版本'
})

onMounted(() => void loadStatus())
onBeforeUnmount(() => {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
})

async function loadStatus(preserveMessage = false) {
  loadingStatus.value = true
  const result = await props.bridge.ludusavi_status()
  loadingStatus.value = false
  if (!result.ok) {
    if (!preserveMessage) message.value = result.error.message
    return
  }
  status.value = result.data
}

async function updateManifest() {
  if (busy.value) return
  updating.value = true
  resultKind.value = null
  message.value = '正在启动 Ludusavi 更新任务……'
  const result = await props.bridge.update_ludusavi({})
  if (!result.ok) {
    updating.value = false
    resultKind.value = 'failed'
    message.value = result.error.message
    return
  }
  await pollTask(result.data.taskId)
}

async function pollTask(taskId: string) {
  const result = await props.bridge.task_snapshot(taskId)
  if (!result.ok) {
    updating.value = false
    resultKind.value = 'failed'
    message.value = result.error.message
    return
  }
  const task = result.data
  if (task.status === 'completed') {
    const updateResult = parseUpdateResult(task.result)
    resultKind.value = updateResult?.status ?? null
    message.value = updateResult?.message || task.message || 'Ludusavi 规则已检查完成。'
    updating.value = false
    await loadStatus(true)
    return
  }
  if (task.status === 'failed' || task.status === 'cancelled') {
    updating.value = false
    resultKind.value = 'failed'
    message.value = task.error?.message ?? 'Ludusavi 更新没有完成，当前版本保持不变。'
    return
  }
  message.value = task.message || '正在更新 Ludusavi 规则……'
  pollTimer = window.setTimeout(() => void pollTask(taskId), 350)
}

async function restoreBundled() {
  if (busy.value) return
  if (!window.confirm('确认恢复随包 Ludusavi 版本吗？这会移除用户更新的活动快照，但不会修改游戏或存档记录。')) return
  restoring.value = true
  resultKind.value = null
  message.value = ''
  const result = await props.bridge.restore_bundled_ludusavi({})
  restoring.value = false
  if (!result.ok) {
    resultKind.value = 'failed'
    message.value = result.error.message
    return
  }
  status.value = result.data
  resultKind.value = 'restored'
  message.value = '已恢复随包 Ludusavi 版本。'
}

async function openRuleDirectory() {
  if (busy.value) return
  opening.value = true
  const result = await props.bridge.open_rule_directory({ target: 'user' })
  opening.value = false
  message.value = result.ok ? '已打开用户规则目录。' : result.error.message
}

function parseUpdateResult(value: unknown): LudusaviUpdateResult | null {
  if (typeof value !== 'object' || value === null || !('status' in value) || !('message' in value)) return null
  const statuses = ['updated', 'not_modified', 'invalid', 'failed'] as const
  if (!statuses.includes(value.status as typeof statuses[number]) || typeof value.message !== 'string') return null
  return value as LudusaviUpdateResult
}
</script>

<template>
  <section data-test="ludusavi-rule-panel" class="ludusavi-rule-panel">
    <div class="rule-pane-heading">
      <div><p>官方社区规则快照</p><h3>Ludusavi</h3></div>
      <strong :class="['ludusavi-source', status?.available ? status.source : 'unavailable']">{{ sourceLabel }}</strong>
    </div>
    <div class="ludusavi-panel-body">
      <p>启动和游戏库扫描不会联网；只有点击“检查更新”才会访问 Ludusavi 更新源。</p>
      <dl v-if="status?.available" class="rule-detail-metadata ludusavi-metadata">
        <dt>当前来源</dt><dd>{{ sourceLabel }}</dd>
        <dt>SHA-256</dt><dd><code>{{ status.sha256?.slice(0, 12) ?? '未知' }}</code></dd>
        <dt>随包摘要</dt><dd><code>{{ status.bundledSha256?.slice(0, 12) ?? '未知' }}</code></dd>
        <dt>获取时间</dt><dd>{{ status.downloadedAt ? new Date(status.downloadedAt).toLocaleString() : '未知' }}</dd>
        <dt>上游提交</dt><dd><code>{{ status.upstreamCommit ?? '未记录' }}</code></dd>
        <dt>更新源</dt><dd class="ludusavi-source-url">{{ status.sourceUrl ?? '未记录' }}</dd>
        <template v-if="status.source === 'bundled'">
          <dt>回退说明</dt><dd>当前使用随包版本；它也是用户活动版本不可用时的安全回退。</dd>
        </template>
      </dl>
      <p v-else-if="status && !status.available" class="manifest-unavailable">
        <strong>Ludusavi 规则不可用</strong><br>{{ status.unavailableReason ?? '没有可用的规则快照。' }}
      </p>
      <p v-else-if="loadingStatus" class="status-message">正在读取本地快照状态……</p>
      <div class="compact-actions ludusavi-actions">
        <button data-test="update-ludusavi" type="button" :disabled="busy" @click="updateManifest">{{ updating ? '正在更新…' : '检查更新' }}</button>
        <button data-test="restore-bundled-ludusavi" class="secondary" type="button" :disabled="busy" @click="restoreBundled">{{ restoring ? '正在恢复…' : '恢复随包版本' }}</button>
        <button data-test="open-rule-directory" class="secondary" type="button" :disabled="busy" @click="openRuleDirectory">打开规则目录</button>
      </div>
      <p v-if="message" data-test="ludusavi-result" :class="['manifest-update-result', resultKind]" aria-live="polite">{{ message }}</p>
    </div>
  </section>
</template>
