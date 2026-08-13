<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { Game, GameShelfBridge } from '../../api/contracts'
import CoverActions from '../covers/CoverActions.vue'
import EngineDetails from '../engines/EngineDetails.vue'
import EnginePicker from '../engines/EnginePicker.vue'
import SaveLocationList from '../saves/SaveLocationList.vue'
import GameSettingsPanel from './GameSettingsPanel.vue'

const props = defineProps<{ game: Game; bridge: GameShelfBridge }>()
const emit = defineEmits<{ close: []; updated: [game: Game]; removed: [gameId: string] }>()
const drawer = ref<HTMLElement | null>(null)
const removalBusy = ref(false)
const removalError = ref('')
let previousBodyPaddingRight = ''

function close() {
  emit('close')
}

function focusableElements(): HTMLElement[] {
  if (!drawer.value) return []
  return Array.from(drawer.value.querySelectorAll<HTMLElement>([
    'button:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    'summary',
    'a[href]',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',')))
}

function trapFocus(event: KeyboardEvent) {
  const focusable = focusableElements()
  const first = focusable.at(0) ?? drawer.value
  const last = focusable.at(-1) ?? drawer.value
  const active = document.activeElement
  if (!drawer.value?.contains(active)) {
    event.preventDefault()
    first?.focus()
  } else if (event.shiftKey && active === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && active === last) {
    event.preventDefault()
    first?.focus()
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') close()
  else if (event.key === 'Tab') trapFocus(event)
}

async function removeGameRecord() {
  const installed = props.game.status === 'installed'
  const prompt = installed
    ? '从游戏库移除并忽略这个目录？不会删除游戏文件；以后扫描该根目录时会跳过它。'
    : '删除这条失效游戏记录？不会删除游戏本体或外部存档，但会移除 GameShelf 管理的封面和存档位置记录。'
  if (!window.confirm(prompt)) return
  removalBusy.value = true
  removalError.value = ''
  const result = installed
    ? await props.bridge.remove_game_and_exclude({ gameId: props.game.id })
    : await props.bridge.delete_missing_game({ gameId: props.game.id })
  removalBusy.value = false
  if (!result.ok) {
    removalError.value = result.error.message
    return
  }
  emit('removed', props.game.id)
}

onMounted(async () => {
  const scrollbarWidth = Math.max(0, window.innerWidth - document.documentElement.clientWidth)
  const currentPadding = Number.parseFloat(window.getComputedStyle(document.body).paddingRight) || 0
  previousBodyPaddingRight = document.body.style.paddingRight
  if (scrollbarWidth > 0) document.body.style.paddingRight = `${currentPadding + scrollbarWidth}px`
  document.documentElement.classList.add('detail-open')
  window.addEventListener('keydown', onKeydown)
  await nextTick()
  drawer.value?.focus()
})

onBeforeUnmount(() => {
  document.documentElement.classList.remove('detail-open')
  document.body.style.paddingRight = previousBodyPaddingRight
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="game-detail-layer">
    <div data-test="drawer-backdrop" class="drawer-backdrop" aria-hidden="true" @click="close" @wheel.prevent />
    <aside ref="drawer" data-test="game-detail-drawer" class="game-drawer" role="dialog" aria-modal="true" :aria-label="`${game.title} 详情`" tabindex="-1">
      <button data-test="drawer-close" class="drawer-close icon-button" type="button" aria-label="关闭游戏详情" @click="close">×</button>
      <div class="detail-cover-frame">
        <img v-if="game.coverOriginalUrl" data-test="detail-cover" :src="game.coverOriginalUrl" :alt="`${game.title} 完整封面`" />
        <div v-else class="cover-placeholder">{{ game.title.slice(0, 1).toUpperCase() }}</div>
      </div>
      <h2>{{ game.title }}</h2>
      <p class="detail-meta">{{ game.engineId ?? '未知引擎' }} · {{ game.status }}</p>
      <EngineDetails
        :adopted="{ id: game.engineId, label: game.engineLabel, variant: game.engineVariant, manual: game.engineIsManual }"
        :detected="game.detectedEngine"
      />
      <EnginePicker :game="game" :bridge="bridge" @updated="$emit('updated', $event)" />
      <CoverActions :game-id="game.id" :has-cover="Boolean(game.coverOriginalUrl)" :bridge="bridge" @updated="$emit('updated', $event)" />
      <SaveLocationList :game-id="game.id" :bridge="bridge" />
      <GameSettingsPanel :game="game" :bridge="bridge" @updated="$emit('updated', $event)" />
      <section v-if="game.status !== 'save_only'" class="record-danger-zone">
        <h3>游戏记录</h3>
        <p v-if="game.status === 'installed'">从库中移除后会自动加入当前根目录排除项，不会删除游戏文件。</p>
        <p v-else>只删除 GameShelf 中的失效记录，不会删除磁盘上的游戏或外部存档。</p>
        <button
          v-if="game.status === 'installed'"
          data-test="remove-game-and-exclude"
          type="button"
          class="danger"
          :disabled="removalBusy"
          @click="removeGameRecord"
        >{{ removalBusy ? '正在移除…' : '从库中移除并忽略' }}</button>
        <button
          v-else
          data-test="delete-missing-game"
          type="button"
          class="danger"
          :disabled="removalBusy"
          @click="removeGameRecord"
        >{{ removalBusy ? '正在删除…' : '删除失效记录' }}</button>
        <p v-if="removalError" class="inline-error" role="alert">{{ removalError }}</p>
      </section>
    </aside>
  </div>
</template>
