<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { EngineOption, Game, GameShelfBridge } from '../../api/contracts'

const props = defineProps<{ game: Game; bridge: GameShelfBridge }>()
const emit = defineEmits<{ updated: [game: Game] }>()
const options = ref<EngineOption[]>([])
const selected = ref(initialSelection())
const customLabel = ref(props.game.engineId?.startsWith('custom:') ? props.game.engineLabel : '')
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const groupedOptions = computed(() => ({
  formal: options.value.filter((item) => !item.experimental),
  experimental: options.value.filter((item) => item.experimental),
}))

function initialSelection() {
  if (props.game.engineIsManual && props.game.engineId === null) return 'unknown'
  if (props.game.engineId?.startsWith('custom:')) return 'custom'
  return props.game.engineId ?? 'unknown'
}

onMounted(async () => {
  const result = await props.bridge.list_engine_options()
  loading.value = false
  if (!result.ok) error.value = result.error.message
  else options.value = result.data
})

async function save() {
  error.value = ''
  const label = customLabel.value.trim()
  if (selected.value === 'custom' && !label) {
    error.value = '请输入自定义引擎名称。'
    return
  }
  saving.value = true
  const request = selected.value === 'custom'
    ? { gameId: props.game.id, engineId: 'custom', customLabel: label }
    : { gameId: props.game.id, engineId: selected.value }
  const result = await props.bridge.set_game_engine(request)
  saving.value = false
  if (!result.ok) error.value = result.error.message
  else emit('updated', result.data)
}

async function restoreAutomatic() {
  saving.value = true
  error.value = ''
  const result = await props.bridge.clear_manual_engine({ gameId: props.game.id })
  saving.value = false
  if (!result.ok) error.value = result.error.message
  else emit('updated', result.data)
}
</script>

<template>
  <section class="engine-picker">
    <label>手动设置引擎
      <select v-model="selected" :disabled="loading || saving">
        <option value="unknown">未知引擎</option>
        <option value="custom">自定义…</option>
        <optgroup label="正式识别器">
          <option v-for="item in groupedOptions.formal" :key="item.id" :value="item.id">{{ item.label }}</option>
        </optgroup>
        <optgroup v-if="groupedOptions.experimental.length" label="实验性识别器">
          <option v-for="item in groupedOptions.experimental" :key="item.id" :value="item.id">{{ item.label }}</option>
        </optgroup>
      </select>
    </label>
    <label v-if="selected === 'custom'">自定义名称
      <input v-model="customLabel" maxlength="80" placeholder="例如：厂商自研引擎" />
    </label>
    <div class="engine-picker-actions">
      <button data-test="save-engine" type="button" :disabled="loading || saving" @click="save">保存引擎</button>
      <button v-if="game.engineIsManual" type="button" class="secondary" :disabled="saving" @click="restoreAutomatic">恢复自动识别</button>
    </div>
    <p v-if="error" role="alert" class="inline-error">{{ error }}</p>
  </section>
</template>
