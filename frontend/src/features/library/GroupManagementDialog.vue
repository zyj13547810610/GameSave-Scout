<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import type { GameGroup, GameShelfBridge } from '../../api/contracts'

const props = defineProps<{ bridge: GameShelfBridge; groups: GameGroup[] }>()
const emit = defineEmits<{ changed: []; close: [] }>()
const newName = ref('')
const error = ref('')
const busyAction = ref('')
const createInput = ref<HTMLInputElement | null>(null)
const draftNames = reactive<Record<string, string>>({})
const groupLimitReached = () => props.groups.length >= 200

watch(
  () => props.groups,
  (groups) => {
    const currentIds = new Set(groups.map((group) => group.id))
    for (const id of Object.keys(draftNames)) {
      if (!currentIds.has(id)) delete draftNames[id]
    }
    for (const group of groups) draftNames[group.id] = group.name
  },
  { immediate: true },
)

async function createGroup() {
  const name = newName.value.trim()
  if (!name || busyAction.value || groupLimitReached()) return
  error.value = ''
  busyAction.value = 'create'
  const result = await props.bridge.create_game_group({ name })
  busyAction.value = ''
  if (!result.ok) {
    error.value = result.error.message
    return
  }
  newName.value = ''
  emit('changed')
  await nextTick()
  createInput.value?.focus()
}

async function renameGroup(group: GameGroup) {
  const name = (draftNames[group.id] ?? '').trim()
  if (!name || name === group.name || busyAction.value) return
  error.value = ''
  busyAction.value = `rename:${group.id}`
  const result = await props.bridge.rename_game_group({ groupId: group.id, name })
  busyAction.value = ''
  if (!result.ok) {
    error.value = result.error.message
    return
  }
  emit('changed')
}

async function deleteGroup(group: GameGroup) {
  if (busyAction.value) return
  const confirmed = window.confirm(
    `确认删除分组“${group.name}”吗？\n\n只会移除分组关系，不会删除任何游戏、封面或存档位置。`,
  )
  if (!confirmed) return
  error.value = ''
  busyAction.value = `delete:${group.id}`
  const result = await props.bridge.delete_game_group({ groupId: group.id })
  busyAction.value = ''
  if (!result.ok) {
    error.value = result.error.message
    return
  }
  emit('changed')
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && !busyAction.value) {
    event.stopImmediatePropagation()
    emit('close')
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown, { capture: true })
  void nextTick(() => createInput.value?.focus())
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown, { capture: true }))
</script>

<template>
  <section
    class="dialog-card group-management-dialog"
    data-test="group-management-dialog"
    role="dialog"
    aria-modal="true"
    aria-labelledby="group-management-title"
  >
    <div class="section-heading">
      <div>
        <h2 id="group-management-title">管理游戏分组</h2>
        <p>一个游戏可以加入多个分组。</p>
      </div>
      <button class="icon-button" type="button" aria-label="关闭分组管理" :disabled="Boolean(busyAction)" @click="$emit('close')">×</button>
    </div>

    <form data-test="create-group-form" class="group-create-form" @submit.prevent="createGroup">
      <label for="new-group-name">新分组名称</label>
      <div>
        <input
          id="new-group-name"
          ref="createInput"
          v-model="newName"
          data-test="new-group-name"
          data-autofocus
          maxlength="40"
          :disabled="groupLimitReached()"
          placeholder="例如 RPG、射击、待游玩"
        />
        <button type="submit" :disabled="!newName.trim() || Boolean(busyAction) || groupLimitReached()">
          {{ busyAction === 'create' ? '正在创建…' : '创建分组' }}
        </button>
      </div>
      <small v-if="groupLimitReached()">最多创建 200 个分组。</small>
      <small v-else>名称最多 40 个字符，不区分英文大小写。</small>
    </form>

    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <div class="group-management-list" aria-label="已有分组">
      <p v-if="groups.length === 0" class="muted">还没有分组。</p>
      <article v-for="group in groups" :key="group.id" class="group-management-row">
        <div class="group-name-field">
          <input
            v-model="draftNames[group.id]"
            :data-test="`group-name-${group.id}`"
            maxlength="40"
            :aria-label="`${group.name} 的新名称`"
          />
          <small>{{ group.gameCount }} 个游戏</small>
        </div>
        <div class="group-row-actions">
          <button
            :data-test="`rename-group-${group.id}`"
            type="button"
            class="secondary"
            :disabled="Boolean(busyAction) || !draftNames[group.id]?.trim() || draftNames[group.id]?.trim() === group.name"
            @click="renameGroup(group)"
          >重命名</button>
          <button
            :data-test="`delete-group-${group.id}`"
            type="button"
            class="danger"
            :disabled="Boolean(busyAction)"
            @click="deleteGroup(group)"
          >删除</button>
        </div>
      </article>
    </div>

    <div class="dialog-actions">
      <button type="button" class="secondary" :disabled="Boolean(busyAction)" @click="$emit('close')">完成</button>
    </div>
  </section>
</template>
