<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { GameGroup, GameShelfBridge, GroupMembershipUpdateResult } from '../../api/contracts'

export type BatchGroupMode = 'add' | 'remove'

const props = defineProps<{
  open: boolean
  groups: GameGroup[]
  selectedGameIds: string[]
  bridge: GameShelfBridge
}>()
const emit = defineEmits<{
  close: []
  applied: [result: GroupMembershipUpdateResult]
  manageGroups: [event: MouseEvent]
}>()
const selectedGroupId = ref('')
const selectedMode = ref<BatchGroupMode>('add')
const busy = ref(false)
const error = ref('')
const groupSelect = ref<HTMLSelectElement | null>(null)
const tooManyGames = computed(() => props.selectedGameIds.length > 500)
const canSubmit = computed(() => (
  Boolean(selectedGroupId.value)
  && props.selectedGameIds.length > 0
  && !tooManyGames.value
  && !busy.value
))

watch(
  () => props.open,
  (open, previous) => {
    if (!open || previous) return
    selectedGroupId.value = ''
    selectedMode.value = 'add'
    error.value = ''
    void nextTick(() => groupSelect.value?.focus())
  },
  { immediate: true },
)

async function submit() {
  if (!canSubmit.value) return
  busy.value = true
  error.value = ''
  const result = await props.bridge.update_game_group_memberships({
    groupId: selectedGroupId.value,
    gameIds: props.selectedGameIds,
    mode: selectedMode.value,
  })
  busy.value = false
  if (!result.ok) {
    error.value = result.error.message
    return
  }
  emit('applied', result.data)
}

function onKeydown(event: KeyboardEvent) {
  if (props.open && event.key === 'Escape' && !busy.value) {
    event.stopImmediatePropagation()
    emit('close')
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown, { capture: true }))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown, { capture: true }))
</script>

<template>
  <section
    v-if="open"
    class="dialog-card batch-group-dialog"
    data-test="batch-group-dialog"
    role="dialog"
    aria-modal="true"
    aria-labelledby="batch-group-title"
  >
    <div class="section-heading">
      <div>
        <h2 id="batch-group-title">批量调整分组</h2>
        <p>将所选 {{ selectedGameIds.length }} 个游戏加入或移出一个分组。</p>
      </div>
      <button class="icon-button" type="button" aria-label="关闭批量分组" :disabled="busy" @click="$emit('close')">×</button>
    </div>

    <form data-test="batch-group-form" @submit.prevent="submit">
      <template v-if="groups.length">
        <label>
          <span>目标分组</span>
          <select ref="groupSelect" v-model="selectedGroupId" data-test="batch-group-select" :disabled="busy">
            <option value="">请选择分组</option>
            <option v-for="group in groups" :key="group.id" :value="group.id">{{ group.name }}（{{ group.gameCount }}）</option>
          </select>
        </label>
        <fieldset class="batch-group-modes" :disabled="busy">
          <legend>操作</legend>
          <label><input v-model="selectedMode" data-test="batch-group-mode-add" type="radio" value="add" /> 加入分组</label>
          <label><input v-model="selectedMode" data-test="batch-group-mode-remove" type="radio" value="remove" /> 移出分组</label>
        </fieldset>
      </template>
      <div v-else class="batch-group-empty">
        <p>还没有分组，请先创建一个分组。</p>
        <button data-test="manage-groups-from-batch" type="button" class="secondary" @click="$emit('manageGroups', $event)">管理分组</button>
      </div>
      <p v-if="tooManyGames" class="form-error" role="alert">一次最多调整 500 个游戏，请减少选择后重试。</p>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <div class="dialog-actions">
        <button type="button" class="secondary" :disabled="busy" @click="$emit('close')">取消</button>
        <button v-if="groups.length" data-test="confirm-batch-group" type="submit" :disabled="!canSubmit">
          {{ busy ? '正在调整…' : selectedMode === 'add' ? '确认加入' : '确认移出' }}
        </button>
      </div>
    </form>
  </section>
</template>
