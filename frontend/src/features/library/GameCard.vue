<script setup lang="ts">
import { ref } from 'vue'
import type { Game } from '../../api/contracts'
import EngineBadge from '../engines/EngineBadge.vue'

withDefaults(defineProps<{
  game: Game
  batchMode?: boolean
  selected?: boolean
}>(), {
  batchMode: false,
  selected: false,
})
defineEmits<{ open: [event: MouseEvent] }>()
const broken = ref(false)
const labels = { installed: '已安装', missing: '本体失效', save_only: '仅存档' }
</script>

<template>
  <button
    :data-test="`game-card-${game.id}`"
    class="cover-card"
    :class="{ 'batch-selected': selected }"
    type="button"
    :aria-pressed="batchMode ? selected : undefined"
    @click="$emit('open', $event)"
  >
    <div class="cover-frame">
      <img v-if="game.coverThumbUrl && !broken" :src="game.coverThumbUrl" :alt="`${game.title} 封面`" loading="lazy" @error="broken = true" />
      <div v-else class="cover-placeholder"><span>{{ game.title.slice(0, 1).toUpperCase() }}</span><small v-if="broken">封面加载失败</small></div>
      <span v-if="batchMode" :data-test="`batch-checkbox-${game.id}`" class="batch-checkbox" aria-hidden="true">{{ selected ? '✓' : '' }}</span>
      <span class="card-badge">{{ labels[game.status] }}</span>
      <span v-if="game.status === 'installed' && !game.mainExeRelpath" class="card-badge no-exe">无 EXE</span>
    </div>
    <strong>{{ game.title }}</strong>
    <small v-if="game.version" class="game-version">{{ game.version }}</small>
    <EngineBadge v-if="game.engineId" :label="game.engineLabel" :experimental="game.engineExperimental" />
  </button>
</template>
