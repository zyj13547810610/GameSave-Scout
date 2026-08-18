<script setup lang="ts">
import { ref, watch } from 'vue'
import type { Game, GameShelfBridge } from '../../api/contracts'

const props = defineProps<{ game: Game; bridge: GameShelfBridge }>()
const emit = defineEmits<{ updated: [game: Game] }>()
const title = ref('')
const version = ref('')
const workingDir = ref('')
const argsText = ref('')
const environmentText = ref('')
const message = ref('')

watch(() => props.game, (game) => {
  title.value = game.title
  version.value = game.version ?? ''
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
  if (result.ok) emit('updated', result.data); else message.value = result.error.message
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
</script>

<template>
  <details open data-test="game-settings-section" class="detail-section game-settings-panel">
    <summary class="detail-section-summary">游戏设置</summary>
    <div class="detail-section-body">
      <div class="game-metadata-fields">
        <label>
          标题
          <input v-model="title" data-test="game-title-input" />
        </label>
        <label>
          版本号
          <input v-model="version" data-test="game-version-input" placeholder="可留空" />
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
      </div>
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
