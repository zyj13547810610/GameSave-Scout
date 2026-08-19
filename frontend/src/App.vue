<script setup lang="ts">
import { createPinia, getActivePinia, storeToRefs } from 'pinia'
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { bridgeKey, createBridge } from './api/bridge'
import type { CoverWizardSettings, Game, LibraryScanSettings, RemovableGameStatus, ScanRoot } from './api/contracts'
import CoverWizardWorkspace from './features/covers/CoverWizardWorkspace.vue'
import BatchManagementBar from './features/library/BatchManagementBar.vue'
import GameGrid from './features/library/GameGrid.vue'
import GroupManagementDialog from './features/library/GroupManagementDialog.vue'
import LibraryToolbar from './features/library/LibraryToolbar.vue'
import { filterGames } from './features/library/libraryFilters'
import { useLibraryStore } from './features/library/libraryStore'
import MoveSuggestionPanel from './features/library/MoveSuggestionPanel.vue'
import UiScaleControl from './features/preferences/UiScaleControl.vue'
import GuidedSaveCloseDialog from './features/saves/GuidedSaveCloseDialog.vue'
import GuidedSaveStatusBar from './features/saves/GuidedSaveStatusBar.vue'
import { useGuidedSaveStore } from './features/saves/guidedSaveStore'
import { applyUiScale, type UiScale } from './features/preferences/uiScale'
import ScanRootDialog from './features/scan-roots/ScanRootDialog.vue'
import ScanRootList from './features/scan-roots/ScanRootList.vue'
import './features/library/library.css'

const bridge = inject(bridgeKey, createBridge())
const pinia = getActivePinia() ?? createPinia()
const store = useLibraryStore(pinia)
const guidedStore = useGuidedSaveStore(pinia)
const {
  roots,
  games,
  groups,
  error,
  scanTasks,
  taskSnapshots,
  moveSuggestions,
  selectedGameId,
} = storeToRefs(store)
const state = ref<'connecting' | 'ready' | 'failed'>('connecting')
const errorMessage = ref('')
const showAddRoot = ref(false)
const editingRoot = ref<ScanRoot | null>(null)
const uiScale = ref<UiScale>(1)
const uiScaleSaveError = ref('')
let uiScaleSaveRevision = 0
const batchMode = ref(false)
const batchBusy = ref(false)
const batchError = ref('')
const batchNotice = ref('')
const showCoverWizard = ref(false)
const showGroupManager = ref(false)
const groupManagerReturnFocus = ref<HTMLElement | null>(null)
const coverWizardEntry = ref<HTMLButtonElement | null>(null)
const gameContentScroll = ref<HTMLElement | null>(null)
const coverWizardSettings = ref<CoverWizardSettings>({
  coverOnlineEnabled: false,
  coverVndbCandidateLimit: 5,
  coverLocalScanCandidateLimit: 10,
})
const libraryScanSettings = ref<LibraryScanSettings>({
  startupQuickScan: true,
  scanConcurrency: 1,
})
const selectedGameIds = ref<Set<string>>(new Set())
const filteredGames = computed(() => filterGames(games.value, {
  query: store.query,
  status: store.statusFilter,
  engine: store.engineFilter,
  group: store.groupFilter,
}))
const engines = computed(() => [...new Set(games.value.map((game) => game.engineId).filter((value): value is string => Boolean(value)))].sort())
const removableGames = computed(() => games.value.filter(isRemovableGame))
const selectedBatchGames = computed(() => removableGames.value.filter((game) => selectedGameIds.value.has(game.id)))
const selectedInstalledCount = computed(() => selectedBatchGames.value.filter((game) => game.status === 'installed').length)
const selectedMissingCount = computed(() => selectedBatchGames.value.filter((game) => game.status === 'missing').length)
const visibleRemovableGames = computed(() => filteredGames.value.filter(isRemovableGame))

function resetGameContentScroll() {
  if (gameContentScroll.value) gameContentScroll.value.scrollTop = 0
}

watch(
  [
    () => store.query,
    () => store.statusFilter,
    () => store.engineFilter,
    () => store.groupFilter,
  ],
  resetGameContentScroll,
)

applyUiScale(uiScale.value, document.documentElement)

async function changeUiScale(scale: UiScale) {
  const revision = ++uiScaleSaveRevision
  uiScale.value = scale
  uiScaleSaveError.value = ''
  applyUiScale(scale, document.documentElement)
  const result = await bridge.set_ui_scale({ uiScale: scale })
  if (revision !== uiScaleSaveRevision) return
  if (!result.ok) uiScaleSaveError.value = result.error.message
}

function isRemovableGame(game: Game): game is Game & { status: RemovableGameStatus } {
  return game.status === 'installed' || game.status === 'missing'
}

function enterBatchMode() {
  selectedGameId.value = null
  batchMode.value = true
  batchError.value = ''
  batchNotice.value = ''
  selectedGameIds.value = new Set()
}

function exitBatchMode() {
  batchMode.value = false
  batchBusy.value = false
  batchError.value = ''
  selectedGameIds.value = new Set()
}

function toggleBatchGame(game: Game) {
  if (!isRemovableGame(game)) return
  const next = new Set(selectedGameIds.value)
  if (next.has(game.id)) next.delete(game.id)
  else next.add(game.id)
  selectedGameIds.value = next
}

function selectVisibleGames() {
  const next = new Set(selectedGameIds.value)
  for (const game of visibleRemovableGames.value) next.add(game.id)
  selectedGameIds.value = next
}

function clearBatchSelection() {
  selectedGameIds.value = new Set()
}

async function removeSelectedGames() {
  const selected = selectedBatchGames.value
  if (selected.length === 0 || batchBusy.value) return
  const installedCount = selectedInstalledCount.value
  const missingCount = selectedMissingCount.value
  const confirmed = window.confirm(
    `确认处理所选 ${selected.length} 个游戏吗？\n\n`
    + `已安装 ${installedCount} 个：从库中移除，并加入各自根目录排除项。\n`
    + `失效 ${missingCount} 个：删除数据库记录。\n\n`
    + '不会删除游戏文件、外部存档或用户原始封面。',
  )
  if (!confirmed) return

  batchBusy.value = true
  batchError.value = ''
  const result = await bridge.remove_games({
    items: selected.map((game) => ({ gameId: game.id, expectedStatus: game.status })),
  })
  if (!result.ok) {
    if (result.error.code === 'invalid_game_state' || result.error.code === 'game_not_found') {
      await store.load(bridge)
      exitBatchMode()
      batchNotice.value = '游戏状态已经变化，请重新选择。'
      return
    }
    batchBusy.value = false
    batchError.value = result.error.message
    return
  }

  await store.load(bridge)
  exitBatchMode()
  batchNotice.value = `已处理 ${result.data.installedCount + result.data.missingCount} 个游戏：`
    + `已安装 ${result.data.installedCount}，失效 ${result.data.missingCount}；`
    + `更新 ${result.data.updatedRootCount} 个根目录排除项。`
  if (result.data.cleanupWarnings.length) {
    batchNotice.value += ` ${result.data.cleanupWarnings.join(' ')}`
  }
}

async function bootstrap() {
  state.value = 'connecting'
  const result = await bridge.bootstrap()
  if (!result.ok) {
    errorMessage.value = result.error.message
    state.value = 'failed'
    return
  }
  uiScale.value = result.data.uiScale
  coverWizardSettings.value = result.data.coverWizardSettings
  libraryScanSettings.value = result.data.libraryScanSettings
  applyUiScale(uiScale.value, document.documentElement)
  await store.load(bridge)
  await guidedStore.refreshActive(bridge)
  state.value = 'ready'
  await nextTick()
  if (libraryScanSettings.value.startupQuickScan) {
    for (const root of roots.value.filter((item) => item.enabled)) {
      void store.scan(bridge, root.id, 'quick')
    }
  }
}

async function rootSaved(root: ScanRoot, created: boolean) {
  showAddRoot.value = false
  editingRoot.value = null
  await store.load(bridge)
  if (created) await store.scan(bridge, root.id, 'full')
}

async function gameRemoved() {
  await store.load(bridge)
}

async function scan(rootId: string) {
  await store.scan(bridge, rootId, 'full')
}

onMounted(bootstrap)
onBeforeUnmount(() => guidedStore.clearPolling())

function openCoverWizard() {
  showGroupManager.value = false
  exitBatchMode()
  selectedGameId.value = null
  showCoverWizard.value = true
}

function openGroupManager(event: MouseEvent) {
  groupManagerReturnFocus.value = event.currentTarget as HTMLElement
  showGroupManager.value = true
}

async function closeGroupManager() {
  showGroupManager.value = false
  await nextTick()
  groupManagerReturnFocus.value?.focus()
}

async function groupsChanged() {
  await store.load(bridge)
}

async function closeCoverWizard() {
  showCoverWizard.value = false
  const latest = await bridge.bootstrap()
  if (latest.ok) coverWizardSettings.value = latest.data.coverWizardSettings
  await nextTick()
  coverWizardEntry.value?.focus()
}

function restoreGuidedSave(gameId: string) {
  batchMode.value = false
  selectedGameId.value = gameId
}
</script>

<template>
  <main class="app-shell">
    <header class="app-header">
      <div><h1>GameShelf</h1><p>便携游戏库与存档管理器</p></div>
      <div class="app-actions">
        <div class="ui-scale-setting">
          <UiScaleControl :model-value="uiScale" @update:model-value="changeUiScale" />
          <p v-if="uiScaleSaveError" class="ui-scale-save-error" data-test="ui-scale-save-error" role="alert">{{ uiScaleSaveError }}</p>
        </div>
        <button v-if="state === 'ready'" type="button" @click="showAddRoot = true">＋ 添加游戏目录</button>
      </div>
    </header>
    <GuidedSaveStatusBar @restore="restoreGuidedSave" />

    <section v-if="state === 'connecting'" class="empty-state" aria-live="polite"><h2>正在连接本地数据库…</h2></section>
    <section v-else-if="state === 'failed'" class="empty-state" role="alert"><h2>无法连接本地数据库</h2><p>{{ errorMessage }}</p><button type="button" @click="bootstrap">重试</button></section>

    <template v-else>
      <div v-if="error" class="error-banner" role="alert"><span>{{ error }}</span><button type="button" @click="store.dismissError">关闭</button></div>
      <div class="library-layout" :inert="showCoverWizard || showGroupManager" :aria-hidden="showCoverWizard || showGroupManager ? 'true' : undefined">
        <ScanRootList :bridge="bridge" :roots="roots" :library-scan-settings="libraryScanSettings" :scan-tasks="scanTasks" :task-snapshots="taskSnapshots" @settings-updated="libraryScanSettings = $event" @scan="scan" @cancel="(id) => store.cancelScan(bridge, id)" @toggle="(root, enabled) => store.updateRoot(bridge, root, enabled)" @edit="editingRoot = $event" @remove="(id) => store.removeRoot(bridge, id)" @remap="(id, path) => store.remapRoot(bridge, id, path)" />
        <section class="library-content">
          <div class="library-fixed-controls" data-test="library-fixed-controls">
            <div class="content-heading">
              <h2>我的游戏 <span>{{ games.length }}</span></h2>
              <div class="compact-actions">
                <button v-if="!batchMode && removableGames.length" data-test="enter-batch-mode" class="secondary" type="button" @click="enterBatchMode">批量管理</button>
                <button ref="coverWizardEntry" data-test="enter-cover-wizard" class="secondary" type="button" @click="openCoverWizard">批量封面</button>
              </div>
            </div>
            <div v-if="batchNotice" data-test="batch-result" class="batch-result" role="status">{{ batchNotice }}</div>
            <BatchManagementBar
              v-if="batchMode"
              :selected-count="selectedBatchGames.length"
              :installed-count="selectedInstalledCount"
              :missing-count="selectedMissingCount"
              :busy="batchBusy"
              :can-select-visible="visibleRemovableGames.length > 0"
              @select-visible="selectVisibleGames"
              @clear="clearBatchSelection"
              @exit="exitBatchMode"
              @remove="removeSelectedGames"
            />
            <p v-if="batchError" class="inline-error" role="alert">{{ batchError }}</p>
            <LibraryToolbar
              v-if="games.length"
              v-model:query="store.query"
              v-model:status="store.statusFilter"
              v-model:engine="store.engineFilter"
              v-model:group="store.groupFilter"
              :engines="engines"
              :groups="groups"
              @manage-groups="openGroupManager"
            />
          </div>
          <div ref="gameContentScroll" class="library-scroll-region" data-test="library-scroll-region" tabindex="0" aria-label="游戏列表">
            <MoveSuggestionPanel :suggestions="moveSuggestions" :games="games" @confirm="store.confirmMove(bridge, $event)" />
            <div v-if="games.length === 0" class="empty-state compact"><h2 id="empty-title">还没有添加游戏目录</h2><p>添加一个或多个本地目录后，游戏会显示在这里。</p><button type="button" @click="showAddRoot = true">添加第一个目录</button></div>
            <template v-else>
              <div v-if="filteredGames.length === 0" class="empty-state compact"><h2>没有符合筛选条件的游戏</h2><p>请调整搜索词或筛选条件。</p></div>
              <GameGrid
                v-else
                :games="filteredGames"
                :groups="groups"
                :bridge="bridge"
                :batch-mode="batchMode"
                :selected-game-ids="selectedGameIds"
                :selected-game-id="selectedGameId"
                @update:selected-game-id="selectedGameId = $event"
                @toggle-selection="toggleBatchGame"
                @updated="store.updateGame"
                @removed="gameRemoved"
                @manage-groups="openGroupManager"
              />
            </template>
          </div>
        </section>
      </div>
      <div v-if="showAddRoot" class="dialog-backdrop" @click.self="showAddRoot = false"><ScanRootDialog :bridge="bridge" @saved="rootSaved" @close="showAddRoot = false" /></div>
      <div v-if="editingRoot" class="dialog-backdrop" @click.self="editingRoot = null"><ScanRootDialog :bridge="bridge" :root="editingRoot" @saved="rootSaved" @close="editingRoot = null" /></div>
      <div v-if="showGroupManager" class="dialog-backdrop" @click.self="closeGroupManager">
        <GroupManagementDialog :bridge="bridge" :groups="groups" @changed="groupsChanged" @close="closeGroupManager" />
      </div>
      <GuidedSaveCloseDialog :bridge="bridge" />
      <CoverWizardWorkspace
        v-if="showCoverWizard"
        :bridge="bridge"
        :games="games"
        :settings="coverWizardSettings"
        @updated="store.updateGame"
        @close="closeCoverWizard"
      />
    </template>
  </main>
</template>
