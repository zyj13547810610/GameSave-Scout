<script setup lang="ts">
import { inject, ref } from 'vue'
import type { Game, GameSaveScoutBridge } from '../../api/contracts'
import { readClipboardPng } from './coverClipboard'

const props = defineProps<{ gameId: string; hasCover: boolean; bridge: GameSaveScoutBridge }>()
const emit = defineEmits<{ updated: [game: Game] }>()
const clipboard = inject<Clipboard>('clipboard', navigator.clipboard)
const busy = ref(false)
const message = ref('')

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
    <div class="compact-actions">
      <button data-test="choose-cover" type="button" :disabled="busy" @click="choose">{{ hasCover ? '替换本地图片' : '选择本地图片' }}</button>
      <button data-test="paste-cover" type="button" :disabled="busy" @click="paste">粘贴截图</button>
      <button v-if="hasCover" data-test="remove-cover" type="button" class="danger" :disabled="busy" @click="remove">移除封面</button>
    </div>
    <p class="status-message" aria-live="polite">{{ busy ? '正在处理封面…' : message }}</p>
  </section>
</template>
