<script setup lang="ts">
import { computed, nextTick, watch } from 'vue'
import type { CoverWizardSettings, Game, GameGroup, GameSaveScoutBridge } from '../../api/contracts'
import GameCard from './GameCard.vue'
import GameDetailDrawer from './GameDetailDrawer.vue'

const props = withDefaults(defineProps<{
  games: Game[]
  bridge: GameSaveScoutBridge
  groups?: GameGroup[]
  batchMode?: boolean
  selectedGameIds?: Set<string>
  selectedGameId?: string | null
  coverSettings?: CoverWizardSettings
}>(), {
  batchMode: false,
  selectedGameIds: () => new Set<string>(),
  selectedGameId: null,
  groups: () => [],
  coverSettings: () => ({
    coverOnlineEnabled: false,
    coverVndbCandidateLimit: 5,
    coverLocalScanCandidateLimit: 10,
    coverOptimizeEnabled: true,
    coverLocalScanDepth: 2,
  }),
})
const emit = defineEmits<{
  updated: [game: Game]
  removed: [gameId: string]
  toggleSelection: [game: Game]
  manageGroups: [event: MouseEvent]
  openRules: [intent: { tab: 'save' | 'ludusavi'; gameId?: string }]
  coverSettingsUpdated: [settings: CoverWizardSettings]
  'update:selectedGameId': [gameId: string | null]
}>()
const selected = computed(
  () => props.games.find((game) => game.id === props.selectedGameId) ?? null,
)
let opener: HTMLElement | null = null

function activate(game: Game, event: Event) {
  if (props.batchMode) {
    emit('toggleSelection', game)
    return
  }
  opener = event.currentTarget as HTMLElement
  emit('update:selectedGameId', game.id)
}

async function close() {
  emit('update:selectedGameId', null)
  await nextTick()
  opener?.focus()
}

function updated(game: Game) {
  emit('update:selectedGameId', game.id)
  emit('updated', game)
}

function removed(gameId: string) {
  emit('update:selectedGameId', null)
  emit('removed', gameId)
}

watch(() => props.batchMode, (enabled) => {
  if (enabled) emit('update:selectedGameId', null)
})
</script>

<template>
  <div data-test="game-grid" class="cover-grid">
    <GameCard
      v-for="game in games"
      :key="game.id"
      :game="game"
      :batch-mode="batchMode"
      :selected="selectedGameIds.has(game.id)"
      @open="activate(game, $event)"
    />
  </div>
  <GameDetailDrawer
    v-if="selected"
    :game="selected"
    :groups="groups"
    :bridge="bridge"
    :cover-settings="coverSettings"
    @close="close"
    @updated="updated"
    @removed="removed"
    @manage-groups="$emit('manageGroups', $event)"
    @open-rules="$emit('openRules', $event)"
    @cover-settings-updated="$emit('coverSettingsUpdated', $event)"
  />
</template>
