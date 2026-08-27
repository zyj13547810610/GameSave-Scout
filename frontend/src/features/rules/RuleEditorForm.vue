<script setup lang="ts">
import { computed, onBeforeUnmount, watch } from 'vue'
import type { EngineCategory, RuleDraft, RuleDraftValidation } from '../../api/contracts'
import EngineRuleForm from './EngineRuleForm.vue'
import SaveRuleForm from './SaveRuleForm.vue'
import RuleYamlPreview from './RuleYamlPreview.vue'

const props = defineProps<{
  draft: RuleDraft
  mode: 'readonly' | 'create' | 'edit'
  validation: RuleDraftValidation | null
  busy: boolean
  dirty: boolean
}>()
const emit = defineEmits<{
  'update:draft': [draft: RuleDraft]
  validate: [draft: RuleDraft]
  test: []
  save: []
}>()
let validationTimer: number | null = null
const structurallyComplete = computed(() => {
  if (!props.draft.id.trim() || !props.draft.label.trim()) return false
  if (props.draft.type === 'engine') {
    return (props.mode !== 'create' || Boolean(props.draft.category))
      && props.draft.all.length + props.draft.any.length > 0
  }
  if (props.draft.locations.length === 0) return false
  return props.draft.type === 'save_game'
    ? props.draft.titles.some((item) => item.trim())
    : props.draft.engine_ids.some((item) => item.trim())
})

function scheduleValidation(draft: RuleDraft) {
  if (validationTimer !== null) window.clearTimeout(validationTimer)
  validationTimer = window.setTimeout(() => {
    validationTimer = null
    emit('validate', draft)
  }, 200)
}

function updateDraft(draft: RuleDraft) {
  emit('update:draft', draft)
  scheduleValidation(draft)
}

function updateCommon(patch: Partial<RuleDraft>) {
  updateDraft({ ...props.draft, ...patch } as RuleDraft)
}

function updateReferences(value: string) {
  updateCommon({ references: value.split(',').map((item) => item.trim()).filter(Boolean) })
}

watch(() => props.draft, (draft, previous) => {
  if (draft !== previous) scheduleValidation(draft)
})
onBeforeUnmount(() => {
  if (validationTimer !== null) window.clearTimeout(validationTimer)
})
</script>

<template>
  <form class="rule-editor-form" @submit.prevent="$emit('save')">
    <fieldset class="rule-editor-group">
      <legend>基本信息</legend>
      <div class="rule-editor-grid">
        <label>规则 ID
          <input name="id" :disabled="mode === 'readonly' || mode === 'edit'" :value="draft.id" @input="updateCommon({ id: ($event.target as HTMLInputElement).value })">
        </label>
        <label>显示名称
          <input name="label" :disabled="mode === 'readonly'" :value="draft.label" @input="updateCommon({ label: ($event.target as HTMLInputElement).value })">
        </label>
        <label>版本
          <input name="version" :disabled="mode === 'readonly'" :value="draft.version" @input="updateCommon({ version: ($event.target as HTMLInputElement).value })">
        </label>
        <label>状态
          <select name="status" :disabled="mode === 'readonly'" :value="draft.status" @change="updateCommon({ status: ($event.target as HTMLSelectElement).value as RuleDraft['status'] })">
            <option value="experimental">实验</option>
            <option value="formal" :disabled="draft.status !== 'formal'">正式/已验证</option>
          </select>
        </label>
        <label>优先级
          <input name="priority" type="number" :disabled="mode === 'readonly'" :value="draft.priority" @input="updateCommon({ priority: Number(($event.target as HTMLInputElement).value) })">
        </label>
        <label>启用状态
          <select name="enabled" :disabled="mode === 'readonly'" :value="draft.enabled ? 'enabled' : 'disabled'" @change="updateCommon({ enabled: ($event.target as HTMLSelectElement).value === 'enabled' })">
            <option value="enabled">已启用</option>
            <option value="disabled">已停用</option>
          </select>
        </label>
        <label v-if="draft.type === 'engine'">适用生态
          <select name="category" :disabled="mode === 'readonly'" :value="draft.category ?? ''" @change="updateCommon({ category: (($event.target as HTMLSelectElement).value || null) as EngineCategory | null })">
            <option value="">未分类{{ mode === 'create' ? '（请选择）' : '' }}</option>
            <option value="general">通用 / 主流游戏</option>
            <option value="visual_novel_doujin">视觉小说 / 同人游戏</option>
          </select>
        </label>
        <label class="rule-editor-wide">备注
          <input name="notes" :disabled="mode === 'readonly'" :value="draft.notes ?? ''" @input="updateCommon({ notes: ($event.target as HTMLInputElement).value || null })">
        </label>
        <label class="rule-editor-wide">参考链接（逗号分隔）
          <input name="references" :disabled="mode === 'readonly'" :value="draft.references.join(', ')" @input="updateReferences(($event.target as HTMLInputElement).value)">
        </label>
      </div>
    </fieldset>

    <EngineRuleForm v-if="draft.type === 'engine'" :model-value="draft" :readonly="mode === 'readonly'" @update:model-value="updateDraft" />
    <SaveRuleForm v-else :model-value="draft" :readonly="mode === 'readonly'" @update:model-value="updateDraft" />

    <p v-if="validation && !validation.valid" class="inline-error" role="alert">
      <code>{{ validation.errorCode }}</code> {{ validation.message }}
    </p>
    <p v-else-if="validation?.valid" class="rule-validation-success">{{ validation.message }}</p>
    <RuleYamlPreview :yaml="validation?.yamlPreview ?? null" />

    <div v-if="mode !== 'readonly'" class="rule-editor-actions">
      <button class="secondary" type="button" @click="$emit('test')">转到本地测试</button>
      <button data-test="save-rule" type="submit" :disabled="busy || !dirty || !validation?.valid || !structurallyComplete">{{ busy ? '正在保存…' : '保存规则' }}</button>
    </div>
  </form>
</template>
