<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { Game, GameShelfBridge } from '../../api/contracts'
import GameCard from './GameCard.vue'
import GameDetailDrawer from './GameDetailDrawer.vue'

const props = withDefaults(defineProps<{
  games: Game[]
  bridge: GameShelfBridge
  batchMode?: boolean
  selectedGameIds?: Set<string>
}>(), {
  batchMode: false,
  selectedGameIds: () => new Set<string>(),
})
const emit = defineEmits<{
  updated: [game: Game]
  removed: [gameId: string]
  toggleSelection: [game: Game]
}>()
const selected = ref<Game | null>(null)
let opener: HTMLElement | null = null

function activate(game: Game, event: Event) {
  if (props.batchMode) {
    if (game.status !== 'save_only') emit('toggleSelection', game)
    return
  }
  opener = event.currentTarget as HTMLElement
  selected.value = game
}

async function close() {
  selected.value = null
  await nextTick()
  opener?.focus()
}

function updated(game: Game) {
  selected.value = game
  emit('updated', game)
}

function removed(gameId: string) {
  selected.value = null
  emit('removed', gameId)
}

watch(() => props.games, (games) => {
  if (selected.value) selected.value = games.find((game) => game.id === selected.value?.id) ?? null
})

watch(() => props.batchMode, (enabled) => {
  if (enabled) selected.value = null
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
  <GameDetailDrawer v-if="selected" :game="selected" :bridge="bridge" @close="close" @updated="updated" @removed="removed" />
</template>
