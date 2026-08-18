<script setup lang="ts">
import { ref, watch } from 'vue'
import type { GameShelfBridge, LibraryScanSettings } from '../../api/contracts'

const props = defineProps<{
  bridge: GameShelfBridge
  settings: LibraryScanSettings
}>()
const emit = defineEmits<{ updated: [settings: LibraryScanSettings] }>()
const startupQuickScan = ref(props.settings.startupQuickScan)
const scanConcurrency = ref<LibraryScanSettings['scanConcurrency']>(props.settings.scanConcurrency)
const saving = ref(false)
const error = ref('')

watch(
  () => props.settings,
  (settings) => {
    if (saving.value) return
    startupQuickScan.value = settings.startupQuickScan
    scanConcurrency.value = settings.scanConcurrency
  },
  { deep: true },
)

async function save() {
  if (saving.value) return
  const requested: LibraryScanSettings = {
    startupQuickScan: startupQuickScan.value,
    scanConcurrency: scanConcurrency.value,
  }
  saving.value = true
  error.value = ''
  const result = await props.bridge.set_library_scan_settings(requested)
  saving.value = false
  if (!result.ok) {
    startupQuickScan.value = props.settings.startupQuickScan
    scanConcurrency.value = props.settings.scanConcurrency
    error.value = result.error.message
    return
  }
  startupQuickScan.value = result.data.startupQuickScan
  scanConcurrency.value = result.data.scanConcurrency
  emit('updated', result.data)
}
</script>

<template>
  <section class="library-scan-settings" data-test="library-scan-settings" aria-label="游戏库扫描设置">
    <label class="check-row">
      <input
        v-model="startupQuickScan"
        data-test="startup-quick-scan"
        type="checkbox"
        :disabled="saving"
        @change="save"
      />
      启动时快速核验
    </label>
    <label class="scan-concurrency-setting">
      <span>并发扫描数</span>
      <select
        v-model.number="scanConcurrency"
        data-test="scan-concurrency"
        :disabled="saving"
        @change="save"
      >
        <option :value="1">1</option>
        <option :value="2">2</option>
        <option :value="3">3</option>
        <option :value="4">4</option>
      </select>
    </label>
    <p v-if="error" data-test="scan-settings-error" class="form-error" role="alert">{{ error }}</p>
  </section>
</template>
