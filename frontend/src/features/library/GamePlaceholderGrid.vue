<script setup lang="ts">
import type { Game } from '../../api/contracts'

defineProps<{ games: Game[]; selectedId?: string }>()
defineEmits<{ select: [game: Game] }>()

const statusLabel = { installed: '已安装', missing: '本体失效', save_only: '仅存档' }
</script>

<template>
  <section class="game-grid" aria-label="游戏库">
    <button v-for="game in games" :key="game.id" type="button" :class="['game-card', { selected: selectedId === game.id }]" @click="$emit('select', game)">
      <div class="cover-placeholder">{{ game.title.slice(0, 1).toUpperCase() }}</div>
      <strong>{{ game.title }}</strong>
      <span>{{ statusLabel[game.status] }}</span>
      <small v-if="!game.mainExeRelpath && game.status === 'installed'">尚未选择主程序</small>
    </button>
  </section>
</template>
