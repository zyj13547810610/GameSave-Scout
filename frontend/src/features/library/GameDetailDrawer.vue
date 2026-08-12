<script setup lang="ts">
import type { Game, GameShelfBridge } from '../../api/contracts'
import CoverActions from '../covers/CoverActions.vue'
import GameSettingsPanel from './GameSettingsPanel.vue'

defineProps<{ game: Game; bridge: GameShelfBridge }>()
defineEmits<{ close: []; updated: [game: Game] }>()
</script>

<template>
  <aside data-test="game-detail-drawer" class="game-drawer" role="dialog" aria-modal="false" :aria-label="`${game.title} 详情`" tabindex="-1" @keydown.esc="$emit('close')">
    <button class="drawer-close icon-button" type="button" aria-label="关闭游戏详情" @click="$emit('close')">×</button>
    <div class="detail-cover-frame">
      <img v-if="game.coverOriginalUrl" data-test="detail-cover" :src="game.coverOriginalUrl" :alt="`${game.title} 完整封面`" />
      <div v-else class="cover-placeholder">{{ game.title.slice(0, 1).toUpperCase() }}</div>
    </div>
    <h2>{{ game.title }}</h2>
    <p class="detail-meta">{{ game.engineId ?? '未知引擎' }} · {{ game.status }}</p>
    <CoverActions :game-id="game.id" :has-cover="Boolean(game.coverOriginalUrl)" :bridge="bridge" @updated="$emit('updated', $event)" />
    <GameSettingsPanel :game="game" :bridge="bridge" @updated="$emit('updated', $event)" @close="$emit('close')" />
  </aside>
</template>
