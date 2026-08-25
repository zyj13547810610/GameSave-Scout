<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Game, GameGroup, GameSaveScoutBridge } from '../../api/contracts'

const props = defineProps<{
  game: Game
  groups: GameGroup[]
  bridge: GameSaveScoutBridge
}>()
const emit = defineEmits<{
  updated: [game: Game]
  manageGroups: [event: MouseEvent]
}>()
const selectedIds = ref<Set<string>>(new Set())
const baselineIds = ref<string[]>([])
const busy = ref(false)
const error = ref('')

const selectedGroupIds = computed(() => props.groups
  .filter((group) => selectedIds.value.has(group.id))
  .map((group) => group.id))
const dirty = computed(() => (
  selectedGroupIds.value.length !== baselineIds.value.length
  || selectedGroupIds.value.some((groupId, index) => groupId !== baselineIds.value[index])
))

watch(
  () => [props.game.id, ...props.game.groupIds],
  () => resetFromGame(),
  { immediate: true },
)

function orderedGroupIds(ids: string[]): string[] {
  const selected = new Set(ids)
  return props.groups.filter((group) => selected.has(group.id)).map((group) => group.id)
}

function resetFromGame() {
  const ordered = orderedGroupIds(props.game.groupIds)
  selectedIds.value = new Set(ordered)
  baselineIds.value = ordered
  error.value = ''
}

function toggle(groupId: string, checked: boolean) {
  const next = new Set(selectedIds.value)
  if (checked) next.add(groupId)
  else next.delete(groupId)
  selectedIds.value = next
}

async function save() {
  if (!dirty.value || busy.value) return
  busy.value = true
  error.value = ''
  const result = await props.bridge.set_game_groups({
    gameId: props.game.id,
    groupIds: selectedGroupIds.value,
  })
  busy.value = false
  if (!result.ok) {
    error.value = result.error.message
    return
  }
  const ordered = orderedGroupIds(result.data.groupIds)
  selectedIds.value = new Set(ordered)
  baselineIds.value = ordered
  emit('updated', result.data)
}
</script>

<template>
  <details data-test="game-groups-section" class="detail-section game-groups-section">
    <summary class="detail-section-summary">
      <span>游戏分组</span>
      <small>{{ game.groupIds.length }} 个</small>
    </summary>
    <div class="detail-section-body">
      <div class="group-section-heading">
        <p v-if="groups.length">可同时选择多个分组。</p>
        <p v-else class="empty-save-message">还没有分组。</p>
        <button
          data-test="manage-groups-from-detail"
          type="button"
          class="secondary"
          @click="$emit('manageGroups', $event)"
        >管理分组</button>
      </div>
      <div v-if="groups.length" class="game-group-options">
        <label v-for="group in groups" :key="group.id" class="game-group-option">
          <input
            :data-test="`game-group-${group.id}`"
            type="checkbox"
            :checked="selectedIds.has(group.id)"
            :disabled="busy"
            @change="toggle(group.id, ($event.target as HTMLInputElement).checked)"
          />
          <span>{{ group.name }}</span>
          <small>{{ group.gameCount }} 个游戏</small>
        </label>
      </div>
      <button
        v-if="groups.length"
        data-test="save-game-groups"
        type="button"
        :disabled="!dirty || busy"
        @click="save"
      >{{ busy ? '正在保存…' : '保存分组' }}</button>
      <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    </div>
  </details>
</template>
