<script setup lang="ts">
import { computed } from 'vue'
import type { Game, GameShelfBridge } from '../../api/contracts'
import EngineDetails from './EngineDetails.vue'
import EnginePicker from './EnginePicker.vue'

const props = defineProps<{ game: Game; bridge: GameShelfBridge }>()
defineEmits<{ updated: [game: Game] }>()

const warning = computed(() => (
  !props.game.detectedEngine || props.game.detectedEngine.ambiguous
))
const modeLabel = computed(() => (
  props.game.engineIsManual ? '手动设置' : '自动识别'
))
const confidenceLabel = computed(() => {
  if (props.game.engineIsManual || !props.game.detectedEngine?.confidence) return ''
  return `${props.game.detectedEngine.confidence}可信度`
})
</script>

<template>
  <details data-test="engine-section" class="detail-section engine-section">
    <summary :class="['detail-section-summary', { warning }]">
      <span>游戏引擎</span>
      <small>{{ [game.engineLabel, modeLabel, confidenceLabel].filter(Boolean).join(' · ') }}</small>
    </summary>
    <div class="detail-section-body">
      <EngineDetails
        :show-heading="false"
        :adopted="{
          id: game.engineId,
          label: game.engineLabel,
          variant: game.engineVariant,
          manual: game.engineIsManual,
        }"
        :detected="game.detectedEngine"
      />
      <EnginePicker
        :game="game"
        :bridge="bridge"
        @updated="$emit('updated', $event)"
      />
    </div>
  </details>
</template>
