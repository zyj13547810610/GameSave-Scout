<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type {
  BatchSaveCandidate,
  EngineOption,
  Game,
  GameGroup,
  GameShelfBridge,
} from '../../api/contracts'

const props = defineProps<{
  open: boolean
  bridge: GameShelfBridge
  groups: GameGroup[]
  candidates: BatchSaveCandidate[]
}>()
const emit = defineEmits<{ created: [game: Game]; close: [] }>()
const title = ref('')
const version = ref('')
const engineId = ref('')
const groupIds = ref(new Set<string>())
const confirmRegistry = ref(false)
const engines = ref<EngineOption[]>([])
const busy = ref(false)
const error = ref('')
const hasRegistry = computed(() => props.candidates.some((item) => item.kind === 'registry'))
const canSubmit = computed(() => (
  title.value.trim()
  && props.candidates.length > 0
  && (!hasRegistry.value || confirmRegistry.value)
  && !busy.value
))

watch(() => props.open, (open) => {
  if (!open) return
  title.value = props.candidates[0]?.suggestedTitle ?? ''
  version.value = ''
  engineId.value = props.candidates[0]?.engineId ?? ''
  groupIds.value = new Set()
  confirmRegistry.value = false
  error.value = ''
}, { immediate: true })

onMounted(async () => {
  const result = await props.bridge.list_engine_options()
  if (result.ok) engines.value = result.data
})

function toggleGroup(groupId: string, selected: boolean) {
  const next = new Set(groupIds.value)
  if (selected) next.add(groupId)
  else next.delete(groupId)
  groupIds.value = next
}

async function submit() {
  if (!canSubmit.value) return
  busy.value = true
  error.value = ''
  const result = await props.bridge.create_batch_save_only_game({
    title: title.value.trim(),
    version: version.value.trim() || null,
    engineId: engineId.value || null,
    groupIds: [...groupIds.value],
    candidateIds: props.candidates.map((item) => item.id),
    confirmRegistry: confirmRegistry.value,
  })
  busy.value = false
  if (!result.ok) error.value = result.error.message
  else emit('created', result.data)
}

function onKeydown(event: KeyboardEvent) {
  if (props.open && event.key === 'Escape' && !busy.value) emit('close')
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <section v-if="open" class="dialog-card save-only-dialog" data-test="save-only-dialog" role="dialog" aria-modal="true" aria-labelledby="save-only-title-heading">
    <div class="section-heading"><div><h2 id="save-only-title-heading">创建仅存档卡片</h2><p>保存标题、分组和 {{ candidates.length }} 个存档位置，不需要游戏本体。</p></div><button type="button" class="icon-button" aria-label="关闭仅存档对话框" :disabled="busy" @click="$emit('close')">×</button></div>
    <form data-test="save-only-form" @submit.prevent="submit">
      <div class="save-only-fields">
        <label>标题<input v-model="title" data-test="save-only-title" maxlength="200" :disabled="busy" required /></label>
        <label>版本（可空）<input v-model="version" maxlength="120" :disabled="busy" /></label>
        <label>引擎（可选）<select v-model="engineId" :disabled="busy"><option value="">未知引擎</option><option v-for="engine in engines" :key="engine.id" :value="engine.id">{{ engine.label }}{{ engine.experimental ? '（实验）' : '' }}</option></select></label>
      </div>
      <fieldset v-if="groups.length" class="save-only-groups" :disabled="busy"><legend>分组（可多选）</legend><label v-for="group in groups" :key="group.id" class="check-row"><input :data-test="`save-only-group-${group.id}`" type="checkbox" :checked="groupIds.has(group.id)" @change="toggleGroup(group.id, ($event.target as HTMLInputElement).checked)" /> {{ group.name }}</label></fieldset>
      <label v-if="hasRegistry" class="registry-confirmation"><input v-model="confirmRegistry" data-test="save-only-confirm-registry" type="checkbox" :disabled="busy" /> 我确认将所选注册表键记录为存档位置；GameShelf 不读取或修改键值。</label>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <div class="dialog-actions"><button type="button" class="secondary" :disabled="busy" @click="$emit('close')">取消</button><button data-test="create-save-only" type="submit" :disabled="!canSubmit">{{ busy ? '正在创建…' : '创建卡片' }}</button></div>
    </form>
  </section>
</template>
