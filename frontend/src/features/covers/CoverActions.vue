<script setup lang="ts">
import { inject, ref, watch } from 'vue'
import type { CoverWizardSettings, Game, GameSaveScoutBridge } from '../../api/contracts'
import { readClipboardPng } from './coverClipboard'

const props = defineProps<{
  gameId: string
  hasCover: boolean
  bridge: GameSaveScoutBridge
  settings: CoverWizardSettings
}>()
const emit = defineEmits<{
  updated: [game: Game]
  settingsUpdated: [settings: CoverWizardSettings]
}>()
const clipboard = inject<Clipboard>('clipboard', navigator.clipboard)
const busy = ref(false)
const message = ref('')
const settingsBusy = ref(false)
const settingsError = ref('')
const optimizeMode = ref(props.settings.coverOptimizeEnabled ? 'optimize' : 'preserve')

watch(
  () => props.settings.coverOptimizeEnabled,
  (enabled) => {
    if (!settingsBusy.value) optimizeMode.value = enabled ? 'optimize' : 'preserve'
  },
)

async function updateOptimizeMode() {
  if (settingsBusy.value) return
  settingsBusy.value = true
  settingsError.value = ''
  try {
    const result = await props.bridge.set_cover_wizard_settings({
      ...props.settings,
      coverOptimizeEnabled: optimizeMode.value === 'optimize',
    })
    if (!result.ok) {
      settingsError.value = result.error.message
      return
    }
    emit('settingsUpdated', result.data)
  } catch {
    settingsError.value = '保存封面设置失败，请稍后重试。'
  } finally {
    settingsBusy.value = false
  }
}

async function choose() {
  if (busy.value) return
  message.value = ''
  const picked = await props.bridge.choose_cover_file({})
  if (!picked.ok) return void (message.value = picked.error.message)
  if (!picked.data) return
  busy.value = true
  const result = await props.bridge.set_cover_from_file({ gameId: props.gameId, selectedPath: picked.data })
  busy.value = false
  finish(result)
}

async function paste() {
  if (busy.value) return
  busy.value = true
  message.value = ''
  try {
    const pngBase64 = await readClipboardPng(clipboard)
    const result = await props.bridge.set_cover_from_clipboard({ gameId: props.gameId, pngBase64 })
    finish(result)
  } catch (error) {
    message.value = error instanceof Error ? error.message : '无法读取剪贴板图片'
  } finally {
    busy.value = false
  }
}

async function remove() {
  if (busy.value || !window.confirm('确定移除这张封面吗？')) return
  busy.value = true
  const result = await props.bridge.remove_cover({ gameId: props.gameId })
  busy.value = false
  finish(result, '封面已移除')
}

function finish(result: Awaited<ReturnType<GameSaveScoutBridge['remove_cover']>>, success = '封面已更新') {
  if (!result.ok) return void (message.value = result.error.message)
  emit('updated', result.data)
  message.value = success
}
</script>

<template>
  <section class="cover-actions">
    <h3>封面</h3>
    <label class="cover-save-mode">封面保存方式
      <select
        v-model="optimizeMode"
        data-test="detail-cover-optimize-mode"
        :disabled="settingsBusy"
        @change="updateOptimizeMode"
      >
        <option value="optimize">自动优化（推荐，最长边 1920px）</option>
        <option value="preserve">保留原尺寸与格式</option>
      </select>
    </label>
    <p v-if="settingsError" class="inline-error" role="alert">设置未保存：{{ settingsError }}</p>
    <div class="compact-actions">
      <button data-test="choose-cover" type="button" :disabled="busy" @click="choose">{{ hasCover ? '替换本地图片' : '选择本地图片' }}</button>
      <button data-test="paste-cover" type="button" :disabled="busy" @click="paste">粘贴截图</button>
      <button v-if="hasCover" data-test="remove-cover" type="button" class="danger" :disabled="busy" @click="remove">移除封面</button>
    </div>
    <p class="status-message" aria-live="polite">{{ busy ? '正在处理封面…' : message }}</p>
  </section>
</template>
