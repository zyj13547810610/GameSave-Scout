<script setup lang="ts">
import { reactive, watch } from 'vue'
import type { CoverWizardSettings } from '../../api/contracts'

const props = defineProps<{
  settings: CoverWizardSettings
  busy?: boolean
  error?: string
}>()
const emit = defineEmits<{ save: [settings: CoverWizardSettings] }>()
const form = reactive({ ...props.settings })
watch(() => props.settings, (value) => Object.assign(form, value), { deep: true })

function submit() {
  emit('save', {
    coverOnlineEnabled: form.coverOnlineEnabled,
    coverVndbCandidateLimit: Number(form.coverVndbCandidateLimit),
    coverLocalScanCandidateLimit: Number(form.coverLocalScanCandidateLimit),
  })
}
</script>

<template>
  <details class="cover-wizard-settings">
    <summary>候选设置</summary>
    <form @submit.prevent="submit">
      <label><input v-model="form.coverOnlineEnabled" type="checkbox"> 启用 VNDB 在线搜索</label>
      <label>每个游戏的 VNDB 候选
        <input v-model.number="form.coverVndbCandidateLimit" type="number" min="1" max="20">
      </label>
      <label>浅层扫描候选
        <input v-model.number="form.coverLocalScanCandidateLimit" type="number" min="1" max="100">
      </label>
      <button type="submit" :disabled="busy">保存设置</button>
      <p v-if="error" class="inline-error" role="alert">设置未保存：{{ error }}</p>
    </form>
  </details>
</template>
