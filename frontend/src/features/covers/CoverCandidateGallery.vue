<script setup lang="ts">
import { ref } from 'vue'
import type { CoverCandidate } from '../../api/contracts'

defineProps<{
  candidates: CoverCandidate[]
  selectedId: string | null
  gameTitle: string
  loading?: boolean
  error?: string
}>()
defineEmits<{ select: [candidateId: string] }>()
const broken = ref(new Set<string>())

function markBroken(id: string) {
  broken.value = new Set(broken.value).add(id)
}
</script>

<template>
  <div v-if="error" class="cover-source-error" role="alert">{{ error }}</div>
  <div v-if="loading" class="cover-gallery-empty" aria-live="polite">正在收集候选…</div>
  <div v-else-if="candidates.length === 0" class="cover-gallery-empty">
    <strong>还没有候选封面</strong>
    <span>可使用上方来源按钮，或把图片拖到工作台中。</span>
  </div>
  <div v-else class="cover-candidate-gallery" role="radiogroup" aria-label="候选封面">
    <button
      v-for="candidate in candidates"
      :key="candidate.id"
      type="button"
      class="cover-candidate-card"
      :class="{ selected: selectedId === candidate.id }"
      role="radio"
      :aria-checked="selectedId === candidate.id"
      @click="$emit('select', candidate.id)"
    >
      <span class="cover-candidate-preview">
        <img
          v-if="candidate.previewUrl && !broken.has(candidate.id)"
          :src="candidate.previewUrl"
          :alt="`${gameTitle} · ${candidate.sourceLabel}候选`"
          @error="markBroken(candidate.id)"
        >
        <span v-else class="cover-candidate-placeholder" aria-label="预览不可用">预览不可用</span>
      </span>
      <span class="cover-candidate-meta">
        <strong>{{ candidate.sourceLabel }}</strong>
        <small>{{ candidate.displayName }}</small>
        <small>{{ candidate.width }} × {{ candidate.height }} · {{ candidate.evidence.join('；') }}</small>
      </span>
    </button>
  </div>
</template>
