<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { BatchSaveCustomRoot, GameShelfBridge } from '../../api/contracts'

const props = defineProps<{ bridge: GameShelfBridge; active: boolean }>()
const emit = defineEmits<{ start: [standardScopeIds: string[], customRootIds: string[]] }>()

const standardScopes = [
  { id: 'documents', label: 'Documents' },
  { id: 'saved_games', label: 'Saved Games' },
  { id: 'app_data', label: 'AppData Roaming' },
  { id: 'local_app_data', label: 'AppData Local' },
  { id: 'local_app_data_low', label: 'AppData LocalLow' },
] as const
const selectedStandard = ref(new Set<string>(standardScopes.map((item) => item.id)))
const customRoots = ref<BatchSaveCustomRoot[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const canStart = computed(() => (
  !props.active
  && !busy.value
  && (selectedStandard.value.size > 0 || customRoots.value.some((item) => item.enabled))
))

onMounted(async () => {
  const result = await props.bridge.bootstrap()
  loading.value = false
  if (!result.ok) error.value = result.error.message
  else customRoots.value = result.data.batchSaveSettings.customRoots
})

function toggleStandard(scopeId: string, selected: boolean) {
  const next = new Set(selectedStandard.value)
  if (selected) next.add(scopeId)
  else next.delete(scopeId)
  selectedStandard.value = next
}

async function addRoot() {
  if (props.active || busy.value) return
  error.value = ''
  const chosen = await props.bridge.choose_batch_save_custom_root()
  if (!chosen.ok) {
    error.value = chosen.error.message
    return
  }
  if (!chosen.data) return
  busy.value = true
  const result = await props.bridge.add_batch_save_custom_root({
    displayPath: chosen.data,
    enabled: true,
    maxDepth: 6,
  })
  busy.value = false
  if (!result.ok) error.value = result.error.message
  else customRoots.value = [...customRoots.value, result.data]
}

async function updateRoot(
  root: BatchSaveCustomRoot,
  changes: { enabled?: boolean; maxDepth?: number },
) {
  if (props.active || busy.value) return
  busy.value = true
  error.value = ''
  const result = await props.bridge.update_batch_save_custom_root({
    rootId: root.id,
    enabled: changes.enabled ?? root.enabled,
    maxDepth: changes.maxDepth ?? root.maxDepth,
  })
  busy.value = false
  if (!result.ok) error.value = result.error.message
  else customRoots.value = customRoots.value.map((item) => (
    item.id === root.id ? result.data : item
  ))
}

async function removeRoot(root: BatchSaveCustomRoot) {
  if (props.active || busy.value) return
  busy.value = true
  error.value = ''
  const result = await props.bridge.remove_batch_save_custom_root({ rootId: root.id })
  busy.value = false
  if (!result.ok) error.value = result.error.message
  else customRoots.value = customRoots.value.filter((item) => item.id !== root.id)
}

function start() {
  if (!canStart.value) return
  const standardIds = standardScopes
    .map((item) => item.id)
    .filter((id) => selectedStandard.value.has(id))
  const customIds = customRoots.value.filter((item) => item.enabled).map((item) => item.id)
  if (!window.confirm(
    `开始扫描所选 ${standardIds.length + customIds.length} 个范围吗？\n\n`
    + '只读取路径、文件名、大小和修改时间等元数据，不读取或修改存档内容。',
  )) return
  emit('start', standardIds, customIds)
}
</script>

<template>
  <details class="batch-save-settings">
    <summary class="batch-save-settings-trigger">扫描设置</summary>
    <section class="batch-save-settings-popover" aria-label="批量存档扫描设置">
      <div class="batch-save-settings-heading">
        <div><strong>扫描范围</strong><small>标准范围只影响本次扫描。</small></div>
        <button data-test="start-batch-scan" type="button" :disabled="!canStart" @click="start">开始扫描</button>
      </div>
      <fieldset :disabled="active || busy || loading">
        <legend>标准范围</legend>
        <label v-for="scope in standardScopes" :key="scope.id" class="check-row">
          <input
            :data-test="`standard-${scope.id}`"
            data-test-kind="standard-scope"
            class="standard-scope-checkbox"
            type="checkbox"
            :checked="selectedStandard.has(scope.id)"
            :disabled="active || busy || loading"
            @change="toggleStandard(scope.id, ($event.target as HTMLInputElement).checked)"
          />
          {{ scope.label }}
        </label>
      </fieldset>
      <div class="batch-custom-roots">
        <div class="batch-custom-heading">
          <strong>自定义目录</strong>
          <button data-test="add-batch-root" type="button" class="secondary" :disabled="active || busy" @click="addRoot">添加目录</button>
        </div>
        <p v-if="customRoots.length === 0" class="muted">尚未添加自定义目录。</p>
        <article v-for="root in customRoots" :key="root.id" class="batch-custom-root">
          <label class="check-row"><input type="checkbox" :checked="root.enabled" :disabled="active || busy" @change="updateRoot(root, { enabled: ($event.target as HTMLInputElement).checked })" /> 参与扫描</label>
          <code>{{ root.displayPath }}</code>
          <label>深度
            <input type="number" min="1" max="12" :value="root.maxDepth" :disabled="active || busy" @change="updateRoot(root, { maxDepth: Number(($event.target as HTMLInputElement).value) })" />
          </label>
          <button type="button" class="danger" :disabled="active || busy" @click="removeRoot(root)">移除</button>
        </article>
      </div>
      <p v-if="active" class="warning-text">扫描运行期间不能修改范围。</p>
      <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    </section>
  </details>
</template>
