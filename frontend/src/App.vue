<script setup lang="ts">
import { createPinia, getActivePinia, storeToRefs } from 'pinia'
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { bridgeKey, createBridge } from './api/bridge'
import type { CoverWizardSettings, Game, GroupMembershipUpdateResult, LibraryScanSettings, RemovableGameStatus, ScanRoot } from './api/contracts'
import CoverWizardWorkspace from './features/covers/CoverWizardWorkspace.vue'
import BatchGroupDialog from './features/library/BatchGroupDialog.vue'
import BatchManagementBar from './features/library/BatchManagementBar.vue'
import GameGrid from './features/library/GameGrid.vue'
import GroupManagementDialog from './features/library/GroupManagementDialog.vue'
import LibraryToolbar from './features/library/LibraryToolbar.vue'
import { filterGames } from './features/library/libraryFilters'
import { useLibraryStore } from './features/library/libraryStore'
import MoveSuggestionPanel from './features/library/MoveSuggestionPanel.vue'
import UiScaleControl from './features/preferences/UiScaleControl.vue'
import BatchSaveStatusBar from './features/saves/BatchSaveStatusBar.vue'
import BatchSaveWorkspace from './features/saves/BatchSaveWorkspace.vue'
import { useBatchSaveStore } from './features/saves/batchSaveStore'
import GuidedSaveCloseDialog from './features/saves/GuidedSaveCloseDialog.vue'
import GuidedSaveStatusBar from './features/saves/GuidedSaveStatusBar.vue'
import { useGuidedSaveStore } from './features/saves/guidedSaveStore'
import { applyUiScale, type UiScale } from './features/preferences/uiScale'
import ScanRootDialog from './features/scan-roots/ScanRootDialog.vue'
import ScanRootList from './features/scan-roots/ScanRootList.vue'
import './features/library/library.css'
import './features/saves/batch-save.css'

const bridge = inject(bridgeKey, createBridge())
const pinia = getActivePinia() ?? createPinia()
const store = useLibraryStore(pinia)
const guidedStore = useGuidedSaveStore(pinia)
const batchSaveStore = useBatchSaveStore(pinia)
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
const activeView = ref<'library' | 'batch_saves'>('library')
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
const showBatchGroup = ref(false)
const batchGroupReturnFocus = ref<HTMLElement | null>(null)
const resumeBatchGroupAfterManagement = ref(false)
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
const selectedGames = computed(() => games.value.filter((game) => selectedGameIds.value.has(game.id)))
const selectedRemovableGames = computed(() => selectedGames.value.filter(isRemovableGame))
const selectedInstalledCount = computed(() => selectedGames.value.filter((game) => game.status === 'installed').length)
const selectedMissingCount = computed(() => selectedGames.value.filter((game) => game.status === 'missing').length)
const selectedSaveOnlyCount = computed(() => selectedGames.value.filter((game) => game.status === 'save_only').length)
const canRemoveSelected = computed(() => selectedGames.value.length > 0 && selectedSaveOnlyCount.value === 0)

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
  showBatchGroup.value = false
  selectedGameIds.value = new Set()
}

function toggleBatchGame(game: Game) {
  const next = new Set(selectedGameIds.value)
  if (next.has(game.id)) next.delete(game.id)
  else next.add(game.id)
  selectedGameIds.value = next
}

function selectVisibleGames() {
  const next = new Set(selectedGameIds.value)
  for (const game of filteredGames.value) next.add(game.id)
  selectedGameIds.value = next
}

function clearBatchSelection() {
  selectedGameIds.value = new Set()
}

async function removeSelectedGames() {
  const selected = selectedRemovableGames.value
  if (!canRemoveSelected.value || batchBusy.value) return
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

function openBatchGroup(event: MouseEvent) {
  if (selectedGames.value.length === 0 || batchBusy.value) return
  batchGroupReturnFocus.value = event.currentTarget as HTMLElement
  batchError.value = ''
  showBatchGroup.value = true
}

async function closeBatchGroup() {
  showBatchGroup.value = false
  await nextTick()
  batchGroupReturnFocus.value?.focus()
}

async function batchGroupsApplied(result: GroupMembershipUpdateResult) {
  const selectedSnapshot = new Set(selectedGameIds.value)
  showBatchGroup.value = false
  batchBusy.value = true
  await store.load(bridge)
  const existingIds = new Set(games.value.map((game) => game.id))
  selectedGameIds.value = new Set([...selectedSnapshot].filter((gameId) => existingIds.has(gameId)))
  batchBusy.value = false
  batchNotice.value = `分组调整完成：已加入 ${result.addedCount}，已移出 ${result.removedCount}，未变化 ${result.unchangedCount}。`
}

function manageGroupsFromBatch() {
  resumeBatchGroupAfterManagement.value = true
  groupManagerReturnFocus.value = null
  showGroupManager.value = true
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
  await batchSaveStore.refreshCurrent(bridge)
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
onBeforeUnmount(() => {
  guidedStore.clearPolling()
  batchSaveStore.clearPolling()
})

function changeView(view: 'library' | 'batch_saves') {
  if (activeView.value === view) return
  selectedGameId.value = null
  showGroupManager.value = false
  showBatchGroup.value = false
  showAddRoot.value = false
  editingRoot.value = null
  exitBatchMode()
  activeView.value = view
}

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
  if (resumeBatchGroupAfterManagement.value) {
    resumeBatchGroupAfterManagement.value = false
    document.querySelector<HTMLElement>('[data-test="manage-groups-from-batch"]')?.focus()
    return
  }
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
  changeView('library')
  batchMode.value = false
  selectedGameId.value = gameId
}
</script>

<template>
  <main class="app-shell">
    <aside class="app-sidebar" :inert="showCoverWizard || showGroupManager || showBatchGroup">
      <div class="app-brand"><h1>GameShelf</h1><p>便携游戏库与存档管理器</p></div>
      <nav class="primary-navigation" aria-label="主要功能">
        <button data-test="nav-library" type="button" :aria-current="activeView === 'library' ? 'page' : undefined" @click="changeView('library')">游戏库</button>
        <button data-test="nav-batch-saves" type="button" :aria-current="activeView === 'batch_saves' ? 'page' : undefined" @click="changeView('batch_saves')">批量存档</button>
      </nav>
      <ScanRootList
        v-if="state === 'ready' && activeView === 'library'"
        :bridge="bridge"
        :roots="roots"
        :library-scan-settings="libraryScanSettings"
        :scan-tasks="scanTasks"
        :task-snapshots="taskSnapshots"
        @settings-updated="libraryScanSettings = $event"
        @scan="scan"
        @cancel="(id) => store.cancelScan(bridge, id)"
        @toggle="(root, enabled) => store.updateRoot(bridge, root, enabled)"
        @edit="editingRoot = $event"
        @remove="(id) => store.removeRoot(bridge, id)"
        @remap="(id, path) => store.remapRoot(bridge, id, path)"
      />
    </aside>

    <section class="app-main">
      <header class="app-header">
        <div class="app-actions">
          <div class="ui-scale-setting">
            <UiScaleControl :model-value="uiScale" @update:model-value="changeUiScale" />
            <p v-if="uiScaleSaveError" class="ui-scale-save-error" data-test="ui-scale-save-error" role="alert">{{ uiScaleSaveError }}</p>
          </div>
          <button v-if="state === 'ready' && activeView === 'library'" data-test="add-game-root" type="button" @click="showAddRoot = true">＋ 添加游戏目录</button>
        </div>
      </header>
      <GuidedSaveStatusBar @restore="restoreGuidedSave" />
      <BatchSaveStatusBar v-if="activeView === 'library'" @restore="changeView('batch_saves')" />

      <section v-if="state === 'connecting'" class="empty-state" aria-live="polite"><h2>正在连接本地数据库…</h2></section>
      <section v-else-if="state === 'failed'" class="empty-state" role="alert"><h2>无法连接本地数据库</h2><p>{{ errorMessage }}</p><button type="button" @click="bootstrap">重试</button></section>

      <template v-else>
        <div v-if="error" class="error-banner" role="alert"><span>{{ error }}</span><button type="button" @click="store.dismissError">关闭</button></div>
        <div v-if="activeView === 'library'" class="library-layout" :inert="showCoverWizard || showGroupManager || showBatchGroup" :aria-hidden="showCoverWizard || showGroupManager || showBatchGroup ? 'true' : undefined">
          <section class="library-content">
          <div class="library-fixed-controls" data-test="library-fixed-controls">
            <div class="content-heading">
              <h2>我的游戏 <span>{{ games.length }}</span></h2>
              <div class="compact-actions">
                <button
                  v-if="games.length"
                  data-test="enter-batch-mode"
                  class="secondary"
                  type="button"
                  :aria-pressed="batchMode"
                  :disabled="batchBusy"
                  @click="batchMode ? exitBatchMode() : enterBatchMode()"
                >{{ batchMode ? '退出批量管理' : '批量管理' }}</button>
                <button ref="coverWizardEntry" data-test="enter-cover-wizard" class="secondary" type="button" @click="openCoverWizard">批量封面</button>
              </div>
            </div>
            <div v-if="batchNotice" data-test="batch-result" class="batch-result" role="status">{{ batchNotice }}</div>
            <BatchManagementBar
              v-if="batchMode"
              :selected-count="selectedGames.length"
              :installed-count="selectedInstalledCount"
              :missing-count="selectedMissingCount"
              :save-only-count="selectedSaveOnlyCount"
              :busy="batchBusy"
              :can-select-visible="filteredGames.length > 0"
              :can-remove="canRemoveSelected"
              @select-visible="selectVisibleGames"
              @clear="clearBatchSelection"
              @group="openBatchGroup"
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
        <BatchSaveWorkspace v-else :bridge="bridge" />
        <div v-if="showAddRoot" class="dialog-backdrop" @click.self="showAddRoot = false"><ScanRootDialog :bridge="bridge" @saved="rootSaved" @close="showAddRoot = false" /></div>
        <div v-if="editingRoot" class="dialog-backdrop" @click.self="editingRoot = null"><ScanRootDialog :bridge="bridge" :root="editingRoot" @saved="rootSaved" @close="editingRoot = null" /></div>
        <div v-if="showGroupManager" class="dialog-backdrop" @click.self="closeGroupManager">
          <GroupManagementDialog :bridge="bridge" :groups="groups" @changed="groupsChanged" @close="closeGroupManager" />
        </div>
        <div v-if="showBatchGroup && !showGroupManager" class="dialog-backdrop" @click.self="closeBatchGroup">
          <BatchGroupDialog
            :open="showBatchGroup && !showGroupManager"
            :bridge="bridge"
            :groups="groups"
            :selected-game-ids="[...selectedGameIds]"
            @applied="batchGroupsApplied"
            @manage-groups="manageGroupsFromBatch"
            @close="closeBatchGroup"
          />
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
    </section>
  </main>
</template>
