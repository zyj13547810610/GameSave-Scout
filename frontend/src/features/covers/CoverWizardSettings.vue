<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import type { CoverWizardSettings } from '../../api/contracts'

const props = defineProps<{
  settings: CoverWizardSettings
  busy?: boolean
  error?: string
}>()
const emit = defineEmits<{ save: [settings: CoverWizardSettings] }>()
const form = reactive({ ...props.settings })
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const open = ref(false)
watch(() => props.settings, (value) => Object.assign(form, value), { deep: true })

async function closeAndRestoreFocus() {
  open.value = false
  await nextTick()
  trigger.value?.focus()
}

function onDocumentPointerDown(event: PointerEvent) {
  if (!open.value || root.value?.contains(event.target as Node)) return
  void closeAndRestoreFocus()
}

onMounted(() => document.addEventListener('pointerdown', onDocumentPointerDown))
onBeforeUnmount(() => document.removeEventListener('pointerdown', onDocumentPointerDown))

function submit() {
  emit('save', {
    coverOnlineEnabled: form.coverOnlineEnabled,
    coverVndbCandidateLimit: Number(form.coverVndbCandidateLimit),
    coverLocalScanCandidateLimit: Number(form.coverLocalScanCandidateLimit),
  })
}
</script>

<template>
  <div ref="root" class="cover-wizard-settings">
    <button
      ref="trigger"
      data-test="cover-settings-trigger"
      class="cover-settings-trigger secondary"
      type="button"
      aria-haspopup="dialog"
      :aria-expanded="open"
      aria-controls="cover-settings-popover"
      @click="open = !open"
    >候选设置</button>
    <section
      v-if="open"
      id="cover-settings-popover"
      data-test="cover-settings-popover"
      class="cover-settings-popover"
      role="dialog"
      aria-label="候选设置"
      @keydown.esc.stop.prevent="closeAndRestoreFocus"
    >
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
    </section>
  </div>
</template>
