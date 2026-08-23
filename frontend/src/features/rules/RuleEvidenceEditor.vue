<script setup lang="ts">
import type { EngineRuleEvidenceDraft } from '../../api/contracts'

const props = defineProps<{
  modelValue: EngineRuleEvidenceDraft[]
  group: 'all' | 'any' | 'negative'
  readonly: boolean
  totalCount: number
}>()
const emit = defineEmits<{ 'update:modelValue': [value: EngineRuleEvidenceDraft[]] }>()

const operations: EngineRuleEvidenceDraft['op'][] = [
  'path_exists', 'glob_exists', 'glob_magic_at', 'magic_at', 'magic_from_end',
  'edge_contains', 'text_contains', 'pe_field_contains',
]
const valueOperations = new Set<EngineRuleEvidenceDraft['op']>([
  'glob_magic_at', 'magic_at', 'magic_from_end', 'edge_contains', 'text_contains', 'pe_field_contains',
])
const offsetOperations = new Set<EngineRuleEvidenceDraft['op']>(['glob_magic_at', 'magic_at', 'magic_from_end'])

function updateItem(index: number, patch: Partial<EngineRuleEvidenceDraft>) {
  const next = props.modelValue.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item)
  emit('update:modelValue', next)
}

function changeOperation(index: number, op: EngineRuleEvidenceDraft['op']) {
  const item = props.modelValue[index]
  if (!item) return
  const next: EngineRuleEvidenceDraft = { op, path: item.path, weight: item.weight }
  if (valueOperations.has(op)) next.value = item.value ?? ''
  if (offsetOperations.has(op)) next.offset = item.offset ?? (op === 'magic_from_end' ? 1 : 0)
  if (op === 'pe_field_contains') next.field = item.field ?? 'product_name'
  emit('update:modelValue', props.modelValue.map((current, itemIndex) => itemIndex === index ? next : current))
}

function addItem() {
  if (props.totalCount >= 64) return
  emit('update:modelValue', [...props.modelValue, { op: 'path_exists', path: '', weight: 1 }])
}

function removeItem(index: number) {
  emit('update:modelValue', props.modelValue.filter((_, itemIndex) => itemIndex !== index))
}

function moveItem(index: number, direction: -1 | 1) {
  const target = index + direction
  if (target < 0 || target >= props.modelValue.length) return
  const next = [...props.modelValue]
  ;[next[index], next[target]] = [next[target]!, next[index]!]
  emit('update:modelValue', next)
}
</script>

<template>
  <fieldset class="rule-editor-group evidence-group">
    <legend>{{ group === 'all' ? '必须满足（all）' : group === 'any' ? '任一满足（any）' : '反向证据（negative）' }}</legend>
    <article v-for="(item, index) in modelValue" :key="index" class="rule-editor-row evidence-row">
      <label>操作
        <select data-test="evidence-op" :disabled="readonly" :value="item.op" @change="changeOperation(index, ($event.target as HTMLSelectElement).value as EngineRuleEvidenceDraft['op'])">
          <option v-for="op in operations" :key="op" :value="op">{{ op }}</option>
        </select>
      </label>
      <label>相对路径
        <input :disabled="readonly" :value="item.path" @input="updateItem(index, { path: ($event.target as HTMLInputElement).value })">
      </label>
      <label v-if="valueOperations.has(item.op)">匹配值
        <input data-test="evidence-value" :disabled="readonly" :value="item.value ?? ''" @input="updateItem(index, { value: ($event.target as HTMLInputElement).value })">
      </label>
      <label v-if="offsetOperations.has(item.op)">偏移
        <input data-test="evidence-offset" type="number" min="0" :disabled="readonly" :value="item.offset ?? 0" @input="updateItem(index, { offset: Number(($event.target as HTMLInputElement).value) })">
      </label>
      <label v-if="item.op === 'pe_field_contains'">PE 字段
        <select :disabled="readonly" :value="item.field ?? 'product_name'" @change="updateItem(index, { field: ($event.target as HTMLSelectElement).value })">
          <option value="product_name">product_name</option>
          <option value="file_description">file_description</option>
          <option value="company_name">company_name</option>
          <option value="architecture">architecture</option>
        </select>
      </label>
      <label>权重
        <input type="number" step="0.01" :disabled="readonly" :value="item.weight" @input="updateItem(index, { weight: Number(($event.target as HTMLInputElement).value) })">
      </label>
      <div v-if="!readonly" class="compact-actions evidence-actions">
        <button class="secondary" type="button" :disabled="index === 0" @click="moveItem(index, -1)">上移</button>
        <button class="secondary" type="button" :disabled="index === modelValue.length - 1" @click="moveItem(index, 1)">下移</button>
        <button :data-test="`remove-evidence-${group}-${index}`" class="danger" type="button" @click="removeItem(index)">删除</button>
      </div>
    </article>
    <button v-if="!readonly" :data-test="`add-evidence-${group}`" class="secondary" type="button" :disabled="totalCount >= 64" @click="addItem">
      添加证据
    </button>
  </fieldset>
</template>
