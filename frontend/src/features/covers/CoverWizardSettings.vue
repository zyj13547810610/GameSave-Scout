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
const popoverPlacement = ref<'above' | 'below'>('below')
const popoverStyle = ref({
  top: 'auto',
  right: 'auto',
  bottom: 'auto',
  left: '1rem',
  width: 'min(24rem, calc(100vw - 2rem))',
  maxHeight: '70dvh',
})
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

function updatePopoverBounds() {
  if (!open.value || !trigger.value) return
  const rect = trigger.value.getBoundingClientRect()
  const gap = 8
  const viewportPadding = 16
  const viewportWidth = window.innerWidth
  const below = Math.max(0, window.innerHeight - rect.bottom - gap - viewportPadding)
  const above = Math.max(0, rect.top - gap - viewportPadding)
  popoverPlacement.value = below < 240 && above > below ? 'above' : 'below'
  const available = popoverPlacement.value === 'above' ? above : below
  const rootFontSize = Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 15
  const width = Math.max(0, Math.min(rootFontSize * 24, viewportWidth - viewportPadding * 2))
  const maxLeft = Math.max(viewportPadding, viewportWidth - viewportPadding - width)
  const left = Math.min(Math.max(rect.right - width, viewportPadding), maxLeft)
  popoverStyle.value = {
    top: popoverPlacement.value === 'below' ? `${Math.round(rect.bottom + gap)}px` : 'auto',
    right: 'auto',
    bottom: popoverPlacement.value === 'above'
      ? `${Math.round(window.innerHeight - rect.top + gap)}px`
      : 'auto',
    left: `${Math.round(left)}px`,
    width: `${Math.floor(width)}px`,
    maxHeight: `${Math.floor(Math.min(window.innerHeight * 0.7, available))}px`,
  }
}

async function toggleOpen() {
  if (open.value) {
    open.value = false
    return
  }
  open.value = true
  await nextTick()
  updatePopoverBounds()
}

function onDocumentPointerDown(event: PointerEvent) {
  if (!open.value || root.value?.contains(event.target as Node)) return
  void closeAndRestoreFocus()
}

onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointerDown)
  window.addEventListener('resize', updatePopoverBounds)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  window.removeEventListener('resize', updatePopoverBounds)
})

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
      @click="toggleOpen"
    >候选设置</button>
    <section
      v-if="open"
      id="cover-settings-popover"
      data-test="cover-settings-popover"
      class="cover-settings-popover"
      :class="`placement-${popoverPlacement}`"
      :style="popoverStyle"
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
