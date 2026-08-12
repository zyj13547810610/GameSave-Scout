<script setup lang="ts">
import type { Game, MoveSuggestion } from '../../api/contracts'

defineProps<{ suggestions: MoveSuggestion[]; games: Game[] }>()
defineEmits<{ confirm: [suggestion: MoveSuggestion] }>()
</script>

<template>
  <section v-if="suggestions.length" class="move-panel">
    <h2>可能移动过的游戏</h2>
    <article v-for="suggestion in suggestions" :key="`${suggestion.sessionId}:${suggestion.existingGameId}`">
      <p><strong>{{ games.find((game) => game.id === suggestion.existingGameId)?.title ?? '失效游戏' }}</strong> 可能已移动到 <code>{{ suggestion.candidateRelativeDir }}</code></p>
      <span>匹配置信度 {{ Math.round(suggestion.confidence * 100) }}%</span>
      <button type="button" @click="$emit('confirm', suggestion)">确认移动并保留原资料</button>
    </article>
  </section>
</template>
