<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
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
const optimizeMode = computed({
  get: () => form.coverOptimizeEnabled ? 'optimize' : 'preserve',
  set: (value: string) => { form.coverOptimizeEnabled = value === 'optimize' },
})
watch(
  () => props.settings,
  (value) => {
    if (!open.value) Object.assign(form, value)
  },
  { deep: true },
)

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
    coverOptimizeEnabled: form.coverOptimizeEnabled,
    coverLocalScanDepth: Number(form.coverLocalScanDepth) as 1 | 2 | 3,
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
        <label>封面保存方式
          <select v-model="optimizeMode" data-test="cover-optimize-mode">
            <option value="optimize">自动优化（推荐，最长边 1920px）</option>
            <option value="preserve">保留原尺寸与格式</option>
          </select>
        </label>
        <label>扫描游戏安装目录层数
          <select v-model.number="form.coverLocalScanDepth" data-test="cover-local-scan-depth">
            <option :value="1">1 层（仅安装目录）</option>
            <option :value="2">2 层（安装目录和直接子目录，默认）</option>
            <option :value="3">3 层（再包含下一层子目录）</option>
          </select>
        </label>
        <button type="submit" :disabled="busy">保存设置</button>
        <p v-if="error" class="inline-error" role="alert">设置未保存：{{ error }}</p>
      </form>
    </section>
  </div>
</template>
