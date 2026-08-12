<script setup lang="ts">
import { ref, watch } from 'vue'
import type { Game, GameShelfBridge } from '../../api/contracts'

const props = defineProps<{ game: Game; bridge: GameShelfBridge }>()
const emit = defineEmits<{ updated: [game: Game]; close: [] }>()
const title = ref('')
const workingDir = ref('')
const argsText = ref('')
const environmentText = ref('')
const message = ref('')

watch(() => props.game, (game) => {
  title.value = game.title
  workingDir.value = game.workingDirRelpath ?? ''
  argsText.value = game.launchArgs.join('\n')
  environmentText.value = Object.entries(game.environment).map(([key, value]) => `${key}=${value}`).join('\n')
}, { immediate: true })

async function saveTitle() {
  const result = await props.bridge.set_game_title({ gameId: props.game.id, title: title.value })
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

async function launch() {
  const result = await props.bridge.launch_game({ gameId: props.game.id })
  message.value = result.ok ? `游戏已启动（PID ${result.data.pid}）` : result.error.message
}
</script>

<template>
  <aside class="settings-panel">
    <div class="section-heading"><h2>游戏设置</h2><button class="icon-button" type="button" @click="$emit('close')">×</button></div>
    <label>标题</label><div class="path-row"><input v-model="title" /><button type="button" @click="saveTitle">保存</button></div>
    <dl><dt>安装路径</dt><dd>{{ game.installPath ?? '未知' }}</dd><dt>主程序</dt><dd>{{ game.mainExeRelpath ?? '尚未选择' }}</dd></dl>
    <div class="dialog-actions"><button type="button" @click="chooseExecutable">选择主程序</button><button type="button" class="secondary" @click="bridge.open_install_directory({ gameId: game.id })">打开文件夹</button><button type="button" :disabled="game.status !== 'installed' || !game.mainExeRelpath" @click="launch">启动</button></div>
    <details><summary>高级启动设置</summary><label>工作目录（相对路径）</label><input v-model="workingDir" placeholder="留空表示游戏目录" /><label>参数（每行一个）</label><textarea v-model="argsText" rows="3" /><label>环境变量（NAME=VALUE）</label><textarea v-model="environmentText" rows="3" /><button type="button" @click="saveAdvanced">保存启动设置</button></details>
    <p v-if="message" class="status-message">{{ message }}</p>
  </aside>
</template>
