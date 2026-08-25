<script setup lang="ts">
import { computed } from 'vue'
import type { SaveLocationKind, SaveRuleLocationDraft } from '../../api/contracts'

const props = defineProps<{ modelValue: SaveRuleLocationDraft; readonly: boolean; index: number }>()
const emit = defineEmits<{ 'update:modelValue': [value: SaveRuleLocationDraft]; remove: []; up: []; down: [] }>()

const filesystemRoots = [
  '<game>', '<home>', '<winAppData>', '<winLocalAppData>', '<winLocalAppDataLow>',
  '<winDocuments>', '<winSavedGames>', '<winProgramData>', '<winPublic>', '<winDir>',
]
const registryRoots = ['HKEY_CURRENT_USER', 'HKEY_LOCAL_MACHINE']
const metadataPlaceholders = [
  '{company_name}', '{product_name}', '{project_name}', '{renpy_save_directory}',
]
const registry = computed(() => props.modelValue.kind === 'registry')
const roots = computed(() => registry.value ? registryRoots : filesystemRoots)
const selectedRoot = computed(() => {
  const normalized = props.modelValue.path.replaceAll('/', '\\')
  return roots.value.find((root) => normalized === root || normalized.startsWith(`${root}\\`)) ?? roots.value[0]!
})
const suffix = computed(() => {
  const normalized = props.modelValue.path.replaceAll('/', '\\')
  return normalized === selectedRoot.value ? '' : normalized.slice(selectedRoot.value.length).replace(/^\\+/, '')
})

function update(patch: Partial<SaveRuleLocationDraft>) {
  emit('update:modelValue', { ...props.modelValue, ...patch })
}

function updatePath(root = selectedRoot.value, relative = suffix.value) {
  update({ path: relative ? `${root}\\${relative}` : root })
}

function changeKind(kind: SaveLocationKind) {
  const nextRoot = kind === 'registry' ? registryRoots[0]! : filesystemRoots[0]!
  update({ kind, path: nextRoot })
}

function insertPlaceholder(placeholder: string) {
  const relative = suffix.value ? `${suffix.value}\\${placeholder}` : placeholder
  updatePath(selectedRoot.value, relative)
}
</script>

<template>
  <article class="rule-editor-row location-row">
    <label>位置类型
      <select data-test="location-kind" :disabled="readonly" :value="modelValue.kind" @change="changeKind(($event.target as HTMLSelectElement).value as SaveLocationKind)">
        <option value="directory">directory</option><option value="file">file</option><option value="glob">glob</option><option value="registry">registry</option>
      </select>
    </label>
    <label>分类
      <select data-test="location-category" :disabled="readonly" :value="modelValue.category" @change="update({ category: ($event.target as HTMLSelectElement).value as SaveRuleLocationDraft['category'] })">
        <option value="save">save</option><option value="config">config</option><option value="other">other</option>
      </select>
    </label>
    <label>显示条件
      <select
        data-test="location-existence-mode"
        :disabled="readonly"
        :value="String(modelValue.require_existing ?? false)"
        @change="update({ require_existing: ($event.target as HTMLSelectElement).value === 'true' })"
      >
        <option value="false">始终建议</option>
        <option value="true">仅找到时显示</option>
      </select>
    </label>
    <label>安全根
      <select data-test="location-root" :disabled="readonly" :value="selectedRoot" @change="updatePath(($event.target as HTMLSelectElement).value)">
        <option v-for="root in roots" :key="root" :value="root">{{ root }}</option>
      </select>
    </label>
    <label>相对模板
      <input :disabled="readonly" :value="suffix" placeholder="目录或文件名" @input="updatePath(selectedRoot, ($event.target as HTMLInputElement).value)">
    </label>
    <label>可信度
      <input type="number" min="0" max="1" step="0.01" :disabled="readonly" :value="modelValue.confidence" @input="update({ confidence: Number(($event.target as HTMLInputElement).value) })">
    </label>
    <div v-if="!readonly && !registry" class="compact-actions placeholder-actions">
      <button v-for="placeholder in metadataPlaceholders" :key="placeholder" class="secondary" type="button" @click="insertPlaceholder(placeholder)">{{ placeholder }}</button>
    </div>
    <p v-if="!registry" class="rule-field-help">
      {renpy_save_directory} 只有在 Ren'Py 安全元数据可用时才会展开。
    </p>
    <div v-if="!readonly" class="compact-actions">
      <button class="secondary" type="button" @click="$emit('up')">上移</button>
      <button class="secondary" type="button" @click="$emit('down')">下移</button>
      <button class="danger" type="button" @click="$emit('remove')">删除位置</button>
    </div>
  </article>
</template>
