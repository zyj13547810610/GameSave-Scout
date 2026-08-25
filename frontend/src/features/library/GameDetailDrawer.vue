<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { Game, GameGroup, GameSaveScoutBridge } from '../../api/contracts'
import CoverActions from '../covers/CoverActions.vue'
import EngineSection from '../engines/EngineSection.vue'
import SaveLocationList from '../saves/SaveLocationList.vue'
import GameSettingsPanel from './GameSettingsPanel.vue'
import GameGroupSection from './GameGroupSection.vue'

const props = withDefaults(defineProps<{
  game: Game
  bridge: GameSaveScoutBridge
  groups?: GameGroup[]
}>(), { groups: () => [] })
const emit = defineEmits<{
  close: []
  updated: [game: Game]
  removed: [gameId: string]
  manageGroups: [event: MouseEvent]
  openRules: [intent: { tab: 'save' | 'ludusavi'; gameId?: string }]
}>()
const drawer = ref<HTMLElement | null>(null)
const quickBusy = ref(false)
const quickMessage = ref('')
const removalBusy = ref(false)
const removalError = ref('')

const statusLabels: Record<Game['status'], string> = {
  installed: '已安装',
  missing: '本体失效',
  save_only: '仅存档',
}

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

async function launchGame() {
  if (quickBusy.value) return
  quickBusy.value = true
  quickMessage.value = ''
  const result = await props.bridge.launch_game({ gameId: props.game.id })
  quickBusy.value = false
  quickMessage.value = result.ok ? '游戏已启动' : result.error.message
}

async function openInstallDirectory() {
  if (quickBusy.value) return
  quickBusy.value = true
  quickMessage.value = ''
  const result = await props.bridge.open_install_directory({ gameId: props.game.id })
  quickBusy.value = false
  quickMessage.value = result.ok ? '已打开安装目录' : result.error.message
}

async function removeGameRecord() {
  const installed = props.game.status === 'installed'
  const prompt = installed
    ? '从游戏库移除并忽略这个目录？不会删除游戏文件；以后扫描该根目录时会跳过它。'
    : '删除这条失效游戏记录？不会删除游戏本体或外部存档，但会移除 GameSave Scout 管理的封面和存档位置记录。'
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
  window.addEventListener('keydown', onKeydown)
  await nextTick()
  drawer.value?.focus()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="game-detail-layer">
    <div data-test="drawer-backdrop" class="drawer-backdrop" aria-hidden="true" @click="close" @wheel.prevent />
    <aside ref="drawer" data-test="game-detail-drawer" class="game-drawer" role="dialog" aria-modal="true" :aria-label="`${game.title} 详情`" tabindex="-1">
      <button data-test="drawer-close" class="drawer-close icon-button" type="button" aria-label="关闭游戏详情" @click="close">×</button>
      <section data-test="detail-overview" class="detail-overview">
        <div class="detail-cover-frame">
          <img v-if="game.coverOriginalUrl" data-test="detail-cover" :src="game.coverOriginalUrl" :alt="`${game.title} 完整封面`" />
          <div v-else class="cover-placeholder">{{ game.title.slice(0, 1).toUpperCase() }}</div>
        </div>
        <div class="detail-title-row">
          <h2>{{ game.title }}</h2>
          <span v-if="game.version" class="detail-version-badge">{{ game.version }}</span>
        </div>
        <div class="detail-badges">
          <span class="detail-status-badge">{{ statusLabels[game.status] }}</span>
          <span class="engine-badge">{{ game.engineLabel }}</span>
        </div>
        <div class="detail-quick-actions">
          <button
            data-test="quick-launch"
            type="button"
            :disabled="quickBusy || game.status !== 'installed' || !game.mainExeRelpath"
            @click="launchGame"
          >启动游戏</button>
          <button
            data-test="quick-open-directory"
            type="button"
            class="secondary"
            :disabled="quickBusy || !game.installPath"
            @click="openInstallDirectory"
          >打开安装目录</button>
        </div>
        <p v-if="quickMessage" data-test="quick-message" class="status-message" aria-live="polite">{{ quickMessage }}</p>
      </section>
      <section data-test="detail-cover-actions" class="detail-cover-actions">
        <CoverActions :game-id="game.id" :has-cover="Boolean(game.coverOriginalUrl)" :bridge="bridge" @updated="$emit('updated', $event)" />
      </section>
      <GameSettingsPanel :game="game" :bridge="bridge" @updated="$emit('updated', $event)" />
      <SaveLocationList
        :game-id="game.id"
        :bridge="bridge"
        @create-game-rule="$emit('openRules', { tab: 'save', gameId: game.id })"
        @open-ludusavi="$emit('openRules', { tab: 'ludusavi' })"
      />
      <GameGroupSection
        :game="game"
        :groups="groups"
        :bridge="bridge"
        @updated="$emit('updated', $event)"
        @manage-groups="$emit('manageGroups', $event)"
      />
      <EngineSection :game="game" :bridge="bridge" @updated="$emit('updated', $event)" />
      <details v-if="game.status !== 'save_only'" data-test="record-section" class="detail-section record-danger-zone">
        <summary class="detail-section-summary danger-summary">
          <span>游戏记录</span>
          <small>{{ game.status === 'installed' ? '移除并忽略' : '删除失效记录' }}</small>
        </summary>
        <div class="detail-section-body">
          <p v-if="game.status === 'installed'">从库中移除后会自动加入当前根目录排除项，不会删除游戏文件。</p>
          <p v-else>只删除 GameSave Scout 中的失效记录，不会删除磁盘上的游戏或外部存档。</p>
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
        </div>
      </details>
    </aside>
  </div>
</template>
