<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { Game, GameShelfBridge } from '../../api/contracts'
import GameCard from './GameCard.vue'
import GameDetailDrawer from './GameDetailDrawer.vue'

const props = defineProps<{ games: Game[]; bridge: GameShelfBridge }>()
const emit = defineEmits<{ updated: [game: Game]; removed: [gameId: string] }>()
const selected = ref<Game | null>(null)
let opener: HTMLElement | null = null

function open(game: Game, event: Event) {
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
</script>

<template>
  <div data-test="game-grid" class="cover-grid">
    <GameCard v-for="game in games" :key="game.id" :game="game" @open="open(game, $event)" />
  </div>
  <GameDetailDrawer v-if="selected" :game="selected" :bridge="bridge" @close="close" @updated="updated" @removed="removed" />
</template>
