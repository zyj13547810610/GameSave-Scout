<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { BatchSaveCandidate, GameShelfBridge } from '../../api/contracts'
import { useLibraryStore } from '../library/libraryStore'
import BatchSaveAssociationDialog from './BatchSaveAssociationDialog.vue'
import BatchSaveBatchBar from './BatchSaveBatchBar.vue'
import BatchSaveCandidateList from './BatchSaveCandidateList.vue'
import BatchSaveEvidence from './BatchSaveEvidence.vue'
import BatchSaveFilters from './BatchSaveFilters.vue'
import BatchSaveProgress from './BatchSaveProgress.vue'
import BatchSaveSettings from './BatchSaveSettings.vue'
import { useBatchSaveStore } from './batchSaveStore'
import SaveOnlyGameDialog from './SaveOnlyGameDialog.vue'

const props = defineProps<{ bridge: GameShelfBridge }>()
const emit = defineEmits<{ libraryChanged: [] }>()
const store = useBatchSaveStore()
const library = useLibraryStore()
const {
  task,
  page,
  total,
  selectedIds,
  selectedCandidateDetails,
  loading,
  actionBusy,
  actionError,
  error,
  notice,
} = storeToRefs(store)
const associationCandidates = ref<BatchSaveCandidate[]>([])
const saveOnlyCandidates = ref<BatchSaveCandidate[]>([])
const inspectedId = ref<string | null>(null)
const active = computed(() => task.value && ['queued', 'running'].includes(task.value.status))
const selected = computed(() => [...selectedIds.value]
  .map((id) => selectedCandidateDetails.value[id] ?? page.value.find((item) => item.id === id))
  .filter((item): item is BatchSaveCandidate => Boolean(item)))
const inspected = computed(() => (
  page.value.find((item) => item.id === inspectedId.value) ?? page.value[0] ?? null
))

watch(page, (items) => {
  if (!items.some((item) => item.id === inspectedId.value)) {
    inspectedId.value = items[0]?.id ?? null
  }
})

onMounted(() => void store.open(props.bridge))
onBeforeUnmount(() => store.clearPolling())

async function startScan(standardScopeIds: string[], customRootIds: string[]) {
  await store.startScan(props.bridge, standardScopeIds, customRootIds)
}

function selectionSummary(candidates: BatchSaveCandidate[]) {
  const count = (kind: BatchSaveCandidate['kind']) => candidates.filter((item) => item.kind === kind).length
  return `候选 ${candidates.length}：目录 ${count('directory')}、文件 ${count('file')}、通配符 ${count('glob')}、注册表 ${count('registry')}。`
}

function confirmWrite(candidates: BatchSaveCandidate[], action: string) {
  const registryCount = candidates.filter((item) => item.kind === 'registry').length
  const registryWarning = registryCount
    ? `\n\n其中包含 ${registryCount} 个注册表键。确认后只把键路径记录为存档位置，不会读取或修改键值。`
    : ''
  return window.confirm(
    `${action}\n\n${selectionSummary(candidates)}${registryWarning}\n\n`
    + 'GameShelf 只更新本地数据库，不会移动、修改或删除实际存档。',
  )
}

async function accept(candidates: BatchSaveCandidate[]) {
  const eligible = candidates.filter((item) => (
    item.reviewStatus === 'pending'
    && item.availability === 'available'
    && Boolean(item.reviewGameId || (item.confidence === 'high' && item.suggestedGameId))
  ))
  if (!eligible.length || !confirmWrite(eligible, '确认添加所选存档位置吗？')) return
  const success = await store.acceptCandidates(
    props.bridge,
    eligible.map((item) => item.id),
    eligible.some((item) => item.kind === 'registry'),
  )
  if (success) emit('libraryChanged')
}

async function ignore(candidates: BatchSaveCandidate[]) {
  const targets = candidates.filter((item) => item.reviewStatus === 'pending')
  if (!targets.length) return
  await store.ignoreCandidates(props.bridge, targets.map((item) => item.id))
}

async function restore(candidates: BatchSaveCandidate[]) {
  const targets = candidates.filter((item) => item.reviewStatus === 'ignored')
  if (!targets.length) return
  await store.restoreCandidates(props.bridge, targets.map((item) => item.id))
}

async function clearUnavailable() {
  const targets = selected.value.filter((item) => item.availability === 'unavailable')
  if (!targets.length || !window.confirm(
    `清除 ${targets.length} 条不可用候选历史吗？\n\n不会删除实际存档或已接受的存档位置。`,
  )) return
  await store.clearUnavailable(props.bridge, targets.map((item) => item.id))
}

function openAssociation(candidates: BatchSaveCandidate[]) {
  associationCandidates.value = candidates.filter((item) => (
    item.availability === 'available' && ['pending', 'ignored'].includes(item.reviewStatus)
  ))
}

async function associationApplied(updatedCount: number) {
  associationCandidates.value = []
  store.notice = `已调整 ${updatedCount} 个候选的游戏关联。`
  await store.loadPage(props.bridge)
}

function openSaveOnly(candidates: BatchSaveCandidate[]) {
  saveOnlyCandidates.value = candidates.filter((item) => (
    item.availability === 'available' && item.reviewStatus === 'pending'
  ))
}

async function saveOnlyCreated() {
  const ids = saveOnlyCandidates.value.map((item) => item.id)
  saveOnlyCandidates.value = []
  store.notice = '仅存档卡片已创建。'
  await store.finishCandidateAction(props.bridge, ids)
  emit('libraryChanged')
}
</script>

<template>
  <section class="batch-save-workspace" data-test="batch-save-workspace" aria-labelledby="batch-save-title">
    <header class="batch-save-heading">
      <div><p>存档工具</p><h1 id="batch-save-title">批量存档发现</h1></div>
      <div class="batch-save-heading-actions">
        <span v-if="active" class="batch-save-active-badge">扫描中</span>
        <BatchSaveSettings :bridge="bridge" :active="Boolean(active)" @start="startScan" />
      </div>
    </header>

    <BatchSaveProgress :task="task" :busy="actionBusy" @cancel="store.cancelScan(bridge)" />
    <BatchSaveFilters :bridge="bridge" />

    <div class="batch-save-results" data-test="batch-save-results" tabindex="0" aria-label="批量存档候选">
      <p v-if="loading" class="batch-results-state">正在加载候选…</p>
      <p v-else-if="page.length === 0" class="batch-results-state">{{ total === 0 ? '当前没有存档候选。' : '当前页没有候选。' }}</p>
      <div v-else class="batch-results-layout">
        <BatchSaveCandidateList
          :bridge="bridge"
          :candidates="page"
          :games="library.games"
          :selected-ids="selectedIds"
          @toggle="(id) => { const candidate = page.find((item) => item.id === id); if (candidate) store.toggleSelection(candidate) }"
          @inspect="inspectedId = $event.id"
          @accept="accept([$event])"
          @associate="openAssociation([$event])"
          @save-only="openSaveOnly([$event])"
          @ignore="ignore([$event])"
          @restore="restore([$event])"
        />
        <BatchSaveEvidence v-if="inspected" class="batch-wide-evidence" :candidate="inspected" />
      </div>
    </div>

    <footer class="batch-save-footer">
      <div class="batch-workspace-feedback">
        <p v-if="notice" class="batch-save-notice" role="status">{{ notice }}</p>
        <p v-if="actionError" class="inline-error" role="alert">{{ actionError }}</p>
        <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
      </div>
      <BatchSaveBatchBar
        :selected="selected"
        :busy="actionBusy"
        @accept="accept(selected)"
        @associate="openAssociation(selected)"
        @save-only="openSaveOnly(selected)"
        @ignore="ignore(selected)"
        @restore="restore(selected)"
        @clear-unavailable="clearUnavailable"
        @clear-selection="store.clearSelection"
      />
    </footer>

    <div v-if="associationCandidates.length" class="dialog-backdrop" @click.self="associationCandidates = []">
      <BatchSaveAssociationDialog
        :open="true"
        :bridge="bridge"
        :games="library.games"
        :candidate-ids="associationCandidates.map((item) => item.id)"
        @applied="associationApplied"
        @close="associationCandidates = []"
      />
    </div>
    <div v-if="saveOnlyCandidates.length" class="dialog-backdrop" @click.self="saveOnlyCandidates = []">
      <SaveOnlyGameDialog
        :open="true"
        :bridge="bridge"
        :groups="library.groups"
        :candidates="saveOnlyCandidates"
        @created="saveOnlyCreated"
        @close="saveOnlyCandidates = []"
      />
    </div>
  </section>
</template>
