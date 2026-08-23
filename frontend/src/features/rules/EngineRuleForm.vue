<script setup lang="ts">
import { computed } from 'vue'
import type { EngineRuleDraft, EngineRuleEvidenceDraft } from '../../api/contracts'
import RuleEvidenceEditor from './RuleEvidenceEditor.vue'

const props = defineProps<{ modelValue: EngineRuleDraft; readonly: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: EngineRuleDraft] }>()
const totalEvidence = computed(() => props.modelValue.all.length + props.modelValue.any.length + props.modelValue.negative.length)

function update(patch: Partial<EngineRuleDraft>) {
  emit('update:modelValue', { ...props.modelValue, ...patch })
}

function updateEvidence(group: 'all' | 'any' | 'negative', value: EngineRuleEvidenceDraft[]) {
  update({ [group]: value })
}
</script>

<template>
  <section class="rule-type-form">
    <div class="rule-editor-grid">
      <label>引擎变体
        <input :disabled="readonly" :value="modelValue.variant ?? ''" @input="update({ variant: ($event.target as HTMLInputElement).value || undefined })">
      </label>
      <label>命中阈值
        <input type="number" min="0" max="1" step="0.01" :disabled="readonly" :value="modelValue.threshold" @input="update({ threshold: Number(($event.target as HTMLInputElement).value) })">
      </label>
    </div>
    <p v-if="totalEvidence === 0" class="inline-error">至少添加一项引擎识别证据。</p>
    <RuleEvidenceEditor :model-value="modelValue.all" group="all" :readonly="readonly" :total-count="totalEvidence" @update:model-value="updateEvidence('all', $event)" />
    <RuleEvidenceEditor :model-value="modelValue.any" group="any" :readonly="readonly" :total-count="totalEvidence" @update:model-value="updateEvidence('any', $event)" />
    <RuleEvidenceEditor :model-value="modelValue.negative" group="negative" :readonly="readonly" :total-count="totalEvidence" @update:model-value="updateEvidence('negative', $event)" />
  </section>
</template>
