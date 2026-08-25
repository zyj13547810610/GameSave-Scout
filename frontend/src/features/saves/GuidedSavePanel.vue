<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { computed, onMounted, ref } from 'vue'
import type { GameSaveScoutBridge, GuidedSavePreview } from '../../api/contracts'
import GuidedSaveDiscoveries from './GuidedSaveDiscoveries.vue'
import { useGuidedSaveStore } from './guidedSaveStore'

const props = defineProps<{ gameId: string; bridge: GameSaveScoutBridge }>()
const emit = defineEmits<{ accepted: [] }>()
const store = useGuidedSaveStore()
const { session, error } = storeToRefs(store)
const preview = ref<GuidedSavePreview | null>(null)
const selectedScopes = ref(new Set<string>())
const additionalDirectories = ref<string[]>([])
const loading = ref(false)
const localMessage = ref('')
const activeStatuses = ['preparing', 'monitoring', 'settling']
const activeOtherGame = computed(
  () => session.value
    && activeStatuses.includes(session.value.status)
    && session.value.gameId !== props.gameId,
)
const currentSession = computed(
  () => session.value?.gameId === props.gameId ? session.value : null,
)

onMounted(() => { void store.refreshForGame(props.bridge, props.gameId) })

async function openPreview() {
  loading.value = true
  localMessage.value = ''
  const result = await props.bridge.preview_guided_save_detection({ gameId: props.gameId })
  loading.value = false
  if (!result.ok) return void (localMessage.value = result.error.message)
  preview.value = result.data
  selectedScopes.value = new Set(
    result.data.scopes
      .filter((scope) => scope.available && scope.defaultSelected)
      .map((scope) => scope.id),
  )
}

function toggleScope(scopeId: string, checked: boolean) {
  const next = new Set(selectedScopes.value)
  if (checked) next.add(scopeId)
  else next.delete(scopeId)
  selectedScopes.value = next
}

async function addDirectory() {
  const result = await props.bridge.choose_directory()
  if (!result.ok) return void (localMessage.value = result.error.message)
  if (result.data && !additionalDirectories.value.includes(result.data)) {
    additionalDirectories.value = [...additionalDirectories.value, result.data]
  }
}

async function start() {
  loading.value = true
  await store.start(
    props.bridge,
    props.gameId,
    [...selectedScopes.value],
    additionalDirectories.value,
  )
  loading.value = false
  if (!store.error) preview.value = null
}

async function cancel() {
  if (!window.confirm('取消本次引导式寻找吗？不会生成候选，也不会删除任何文件。')) return
  await store.cancel(props.bridge)
}

function resetTerminal() {
  store.session = null
  store.discoveries = []
  void openPreview()
}
</script>

<template>
  <section class="guided-save-panel">
    <div class="save-location-heading">
      <h4>引导式寻找存档</h4>
      <button
        v-if="!currentSession && !preview"
        data-test="open-guided-preview"
        type="button"
        class="secondary"
        :disabled="loading || Boolean(activeOtherGame)"
        @click="openPreview"
      >引导式寻找</button>
    </div>

    <p v-if="activeOtherGame" class="empty-save-message">
      正在为《{{ session?.gameTitle }}》寻找存档，请先返回该向导完成或取消会话。
    </p>

    <div v-else-if="preview" class="guided-scope-preview">
      <p>将启动：<code>{{ preview.executable }}</code></p>
      <p class="guided-privacy">{{ preview.privacyNotice }}</p>
      <fieldset>
        <legend>选择监控范围</legend>
        <label v-for="scope in preview.scopes" :key="scope.id" class="guided-scope-option">
          <input
            :data-test="`guided-scope-${scope.id}`"
            type="checkbox"
            :disabled="!scope.available"
            :checked="selectedScopes.has(scope.id)"
            @change="toggleScope(scope.id, ($event.target as HTMLInputElement).checked)"
          >
          <span><strong>{{ scope.label }}</strong><small>{{ scope.displayPath }}</small><small v-if="scope.unavailableReason" class="warning-text">{{ scope.unavailableReason }}</small></span>
        </label>
      </fieldset>
      <div v-if="preview.registryTargets.length" class="guided-registry-targets">
        <strong>定向注册表键</strong>
        <code v-for="target in preview.registryTargets" :key="target.key">{{ target.key }}</code>
      </div>
      <div v-if="additionalDirectories.length" class="guided-extra-directories">
        <strong>额外目录</strong>
        <code v-for="directory in additionalDirectories" :key="directory">{{ directory }}</code>
      </div>
      <div class="compact-actions">
        <button type="button" class="secondary" :disabled="loading" @click="addDirectory">添加额外目录</button>
        <button type="button" class="secondary" :disabled="loading" @click="preview = null">返回</button>
        <button data-test="confirm-guided-start" type="button" :disabled="loading" @click="start">确认开始</button>
      </div>
    </div>

    <div v-else-if="currentSession?.status === 'preparing'" class="guided-session-state">
      <strong>正在准备监控</strong><p>观察器全部就绪后才会启动游戏。</p>
    </div>
    <div v-else-if="currentSession?.status === 'monitoring'" class="guided-session-state">
      <strong>正在监控《{{ currentSession.gameTitle }}》的文件变化</strong>
      <p>请在游戏中完成一次存档，然后回到这里继续。</p>
      <p v-if="currentSession.processTrackingDegraded" class="warning-text" role="status">
        无法可靠判断游戏是否仍在运行，监控将继续；请在完成存档后手动操作。
      </p>
      <div class="compact-actions">
        <button data-test="guided-mark-saved" type="button" @click="store.markSaved(bridge)">我刚刚保存了</button>
        <button data-test="guided-stop-analyze" type="button" class="secondary" @click="store.stopAndAnalyze(bridge)">停止并分析</button>
        <button data-test="guided-cancel" type="button" class="danger" @click="cancel">取消会话</button>
      </div>
    </div>
    <div v-else-if="currentSession?.status === 'settling'" class="guided-session-state">
      <strong>正在等待游戏完成写盘</strong><p>约 3 秒后自动停止监控并分析变化，请勿重复操作。</p>
    </div>
    <GuidedSaveDiscoveries
      v-else-if="currentSession?.status === 'completed'"
      :bridge="bridge"
      @accepted="emit('accepted')"
    />
    <div v-else-if="currentSession" class="guided-session-state">
      <strong>本次引导式寻找已{{ currentSession.status === 'cancelled' ? '取消' : currentSession.status === 'interrupted' ? '中断' : '失败' }}</strong>
      <p v-if="currentSession.error">{{ currentSession.error.message }}</p>
      <button type="button" class="secondary" @click="resetTerminal">重新开始</button>
    </div>
    <p v-else-if="!preview" class="empty-save-message">由 GameSave Scout 启动游戏并观察一次存档前后的本地元数据变化。</p>

    <p v-if="localMessage || error" class="status-message" role="alert">{{ localMessage || error }}</p>
  </section>
</template>
