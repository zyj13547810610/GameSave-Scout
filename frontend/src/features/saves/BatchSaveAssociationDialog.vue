<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Game, GameSaveScoutBridge } from '../../api/contracts'

const props = defineProps<{
  open: boolean
  bridge: GameSaveScoutBridge
  games: Game[]
  candidateIds: string[]
}>()
const emit = defineEmits<{ applied: [updatedCount: number]; close: [] }>()
const selectedGameId = ref('')
const busy = ref(false)
const error = ref('')
const select = ref<HTMLSelectElement | null>(null)

watch(() => props.open, (open) => {
  if (!open) return
  selectedGameId.value = ''
  error.value = ''
  void nextTick(() => select.value?.focus())
}, { immediate: true })

async function submit() {
  if (!selectedGameId.value || busy.value || props.candidateIds.length === 0) return
  busy.value = true
  error.value = ''
  const result = await props.bridge.reassociate_batch_save_candidates({
    candidateIds: props.candidateIds,
    gameId: selectedGameId.value,
  })
  busy.value = false
  if (!result.ok) error.value = result.error.message
  else emit('applied', result.data.updatedCount)
}

function onKeydown(event: KeyboardEvent) {
  if (props.open && event.key === 'Escape' && !busy.value) emit('close')
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <section v-if="open" class="dialog-card batch-association-dialog" data-test="association-dialog" role="dialog" aria-modal="true" aria-labelledby="association-title">
    <div class="section-heading"><div><h2 id="association-title">调整游戏关联</h2><p>把 {{ candidateIds.length }} 个候选关联到同一个游戏。</p></div><button type="button" class="icon-button" aria-label="关闭关联对话框" :disabled="busy" @click="$emit('close')">×</button></div>
    <form data-test="association-form" @submit.prevent="submit">
      <label>目标游戏
        <select ref="select" v-model="selectedGameId" data-test="association-game" :disabled="busy">
          <option value="">请选择游戏</option>
          <option v-for="game in games" :key="game.id" :value="game.id">{{ game.title }}{{ game.version ? ` ${game.version}` : '' }} · {{ game.status === 'save_only' ? '仅存档' : game.status === 'missing' ? '本体失效' : '已安装' }}</option>
        </select>
      </label>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <div class="dialog-actions"><button type="button" class="secondary" :disabled="busy" @click="$emit('close')">取消</button><button type="submit" :disabled="!selectedGameId || busy">{{ busy ? '正在关联…' : '确认关联' }}</button></div>
    </form>
  </section>
</template>
