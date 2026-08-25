<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import type { Game, GameSaveScoutBridge } from '../../api/contracts'

const props = defineProps<{ game: Game; bridge: GameSaveScoutBridge }>()
const emit = defineEmits<{ updated: [game: Game] }>()
const title = ref('')
const version = ref('')
const workingDir = ref('')
const argsText = ref('')
const environmentText = ref('')
const message = ref('')
const metadataDirty = ref(false)
const reanalysisBusy = ref(false)
const reanalysisTaskId = ref<string | null>(null)
const reanalysisMessage = ref('')
const reanalysisError = ref('')
let reanalysisTimer: number | undefined
let reanalysisRevision = 0

watch(() => props.game, (game, previous) => {
  if (previous && previous.id !== game.id) stopReanalysisPolling()
  if (!metadataDirty.value || (previous && previous.id !== game.id)) {
    title.value = game.title
    version.value = game.version ?? ''
    metadataDirty.value = false
  }
  workingDir.value = game.workingDirRelpath ?? ''
  argsText.value = game.launchArgs.join('\n')
  environmentText.value = Object.entries(game.environment).map(([key, value]) => `${key}=${value}`).join('\n')
}, { immediate: true })

async function saveMetadata() {
  message.value = ''
  const cleanVersion = version.value.trim()
  const result = await props.bridge.set_game_metadata({
    gameId: props.game.id,
    title: title.value.trim(),
    version: cleanVersion || null,
  })
  if (result.ok) {
    metadataDirty.value = false
    title.value = result.data.title
    version.value = result.data.version ?? ''
    emit('updated', result.data)
  } else message.value = result.error.message
}

async function chooseExecutable() {
  const chosen = await props.bridge.choose_game_executable({ gameId: props.game.id })
  if (!chosen.ok || !chosen.data) return
  const result = await props.bridge.set_game_executable({ gameId: props.game.id, selectedPath: chosen.data })
  if (result.ok) emit('updated', result.data); else message.value = result.error.message
}

async function saveAdvanced() {
  const environment: Record<string, string> = {}
  for (const line of environmentText.value.split(/\r?\n/).filter(Boolean)) {
    const separator = line.indexOf('=')
    if (separator < 1) return void (message.value = '环境变量格式应为 NAME=VALUE')
    environment[line.slice(0, separator)] = line.slice(separator + 1)
  }
  const result = await props.bridge.update_launch_configuration({
    gameId: props.game.id,
    workingDirRelpath: workingDir.value || null,
    launchArgs: argsText.value.split(/\r?\n/).filter(Boolean),
    environment,
  })
  if (result.ok) emit('updated', result.data); else message.value = result.error.message
}

async function openInstallDirectory() {
  const result = await props.bridge.open_install_directory({ gameId: props.game.id })
  if (!result.ok) message.value = result.error.message
}

async function startReanalysis() {
  if (reanalysisBusy.value) return
  stopReanalysisPolling()
  const revision = reanalysisRevision
  reanalysisBusy.value = true
  reanalysisError.value = ''
  reanalysisMessage.value = '正在提交重新检测任务…'
  const result = await props.bridge.start_game_reanalysis({ gameId: props.game.id })
  if (revision !== reanalysisRevision) return
  if (!result.ok) {
    reanalysisBusy.value = false
    reanalysisMessage.value = ''
    reanalysisError.value = result.error.message
    return
  }
  reanalysisTaskId.value = result.data.taskId
  await pollReanalysis(result.data.taskId, props.game.id, revision)
}

async function pollReanalysis(taskId: string, gameId: string, revision: number) {
  const result = await props.bridge.task_snapshot(taskId)
  if (revision !== reanalysisRevision || reanalysisTaskId.value !== taskId) return
  if (!result.ok) {
    finishReanalysis(result.error.message)
    return
  }
  const snapshot = result.data
  reanalysisMessage.value = snapshot.message
  if (snapshot.status === 'queued' || snapshot.status === 'running') {
    reanalysisTimer = window.setTimeout(
      () => void pollReanalysis(taskId, gameId, revision),
      350,
    )
    return
  }
  if (snapshot.status === 'completed') {
    if (!isGameTaskResult(snapshot.result, gameId)) {
      finishReanalysis('重新检测返回了无效结果。')
      return
    }
    const updated = snapshot.result
    finishReanalysis()
    emit('updated', updated)
    return
  }
  if (snapshot.status === 'cancelled') {
    finishReanalysis('重新检测已取消。')
    return
  }
  finishReanalysis(snapshot.error?.message ?? '重新检测失败。')
}

async function cancelReanalysis() {
  const taskId = reanalysisTaskId.value
  if (!taskId) return
  const result = await props.bridge.cancel_task(taskId)
  if (!result.ok) reanalysisError.value = result.error.message
  else reanalysisMessage.value = result.data.cancelled ? '正在取消重新检测…' : '任务已经结束。'
}

function finishReanalysis(error = '') {
  if (reanalysisTimer !== undefined) window.clearTimeout(reanalysisTimer)
  reanalysisTimer = undefined
  reanalysisBusy.value = false
  reanalysisTaskId.value = null
  reanalysisError.value = error
  if (error) reanalysisMessage.value = ''
}

function stopReanalysisPolling() {
  reanalysisRevision += 1
  finishReanalysis()
  reanalysisMessage.value = ''
}

function isGameTaskResult(value: unknown, gameId: string): value is Game {
  if (!isRecord(value)) return false
  const game = value as Partial<Game>
  return game.id === gameId
    && nullableString(game.scanRootId)
    && nullableString(game.relativeDir)
    && nullableString(game.installPath)
    && typeof game.title === 'string'
    && nullableString(game.version)
    && (game.status === 'installed' || game.status === 'missing' || game.status === 'save_only')
    && nullableString(game.engineId)
    && nullableString(game.engineVariant)
    && typeof game.engineLabel === 'string'
    && typeof game.engineExperimental === 'boolean'
    && typeof game.engineIsManual === 'boolean'
    && (game.detectedEngine === null || isRecord(game.detectedEngine))
    && nullableString(game.mainExeRelpath)
    && typeof game.mainExeIsManual === 'boolean'
    && nullableString(game.workingDirRelpath)
    && Array.isArray(game.launchArgs)
    && game.launchArgs.every((item) => typeof item === 'string')
    && isStringRecord(game.environment)
    && (game.exeArch === 'x86' || game.exeArch === 'x64' || game.exeArch === 'unknown')
    && typeof game.coverRevision === 'number'
    && nullableString(game.coverThumbUrl)
    && nullableString(game.coverOriginalUrl)
    && nullableString(game.lastLaunchedAt)
    && nullableString(game.missingSince)
    && Array.isArray(game.groupIds)
    && game.groupIds.every((groupId) => typeof groupId === 'string')
}

function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return isRecord(value) && Object.values(value).every((item) => typeof item === 'string')
}

onBeforeUnmount(stopReanalysisPolling)
</script>

<template>
  <details open data-test="game-settings-section" class="detail-section game-settings-panel">
    <summary class="detail-section-summary">游戏设置</summary>
    <div class="detail-section-body">
      <div class="game-metadata-fields">
        <label>
          标题
          <input v-model="title" data-test="game-title-input" @input="metadataDirty = true" />
        </label>
        <label>
          版本号
          <input v-model="version" data-test="game-version-input" placeholder="可留空" @input="metadataDirty = true" />
        </label>
        <button data-test="save-game-metadata" type="button" @click="saveMetadata">保存标题与版本号</button>
      </div>
      <dl class="game-paths">
        <dt>安装路径</dt>
        <dd>
          <button
            data-test="install-path"
            type="button"
            class="path-link"
            :disabled="!game.installPath"
            @click="openInstallDirectory"
          >{{ game.installPath ?? '未知' }}</button>
        </dd>
        <dt>主程序</dt>
        <dd>{{ game.mainExeRelpath ?? '尚未选择' }}</dd>
      </dl>
      <div class="compact-actions">
        <button type="button" @click="chooseExecutable">
          {{ game.mainExeRelpath ? '重新选择主程序' : '选择主程序' }}
        </button>
        <button
          data-test="reanalyze-game"
          type="button"
          class="secondary"
          :disabled="reanalysisBusy || game.status !== 'installed' || !game.installPath"
          @click="startReanalysis"
        >{{ reanalysisBusy ? '正在重新检测…' : '重新检测主程序和引擎' }}</button>
        <button
          v-if="reanalysisBusy"
          data-test="cancel-reanalysis"
          type="button"
          class="danger"
          @click="cancelReanalysis"
        >取消检测</button>
      </div>
      <p v-if="reanalysisMessage" data-test="reanalysis-message" class="reanalysis-message" aria-live="polite">{{ reanalysisMessage }}</p>
      <p v-if="reanalysisError" data-test="reanalysis-error" class="inline-error" role="alert">{{ reanalysisError }}</p>
      <details class="advanced-settings">
        <summary>高级启动设置</summary>
        <label>工作目录（相对路径）</label>
        <input v-model="workingDir" placeholder="留空表示游戏目录" />
        <label>参数（每行一个）</label>
        <textarea v-model="argsText" rows="3" />
        <label>环境变量（NAME=VALUE）</label>
        <textarea v-model="environmentText" rows="3" />
        <button type="button" @click="saveAdvanced">保存启动设置</button>
      </details>
      <p v-if="message" class="status-message" aria-live="polite">{{ message }}</p>
    </div>
  </details>
</template>
