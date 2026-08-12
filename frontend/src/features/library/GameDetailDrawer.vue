<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { Game, GameShelfBridge } from '../../api/contracts'
import CoverActions from '../covers/CoverActions.vue'
import GameSettingsPanel from './GameSettingsPanel.vue'

defineProps<{ game: Game; bridge: GameShelfBridge }>()
const emit = defineEmits<{ close: []; updated: [game: Game] }>()
const drawer = ref<HTMLElement | null>(null)
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
      <CoverActions :game-id="game.id" :has-cover="Boolean(game.coverOriginalUrl)" :bridge="bridge" @updated="$emit('updated', $event)" />
      <GameSettingsPanel :game="game" :bridge="bridge" @updated="$emit('updated', $event)" />
    </aside>
  </div>
</template>
