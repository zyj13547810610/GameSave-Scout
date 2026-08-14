<script setup lang="ts">
import { createPinia, getActivePinia, storeToRefs } from 'pinia'
import { computed, inject, nextTick, onMounted, ref } from 'vue'
import { bridgeKey, createBridge } from './api/bridge'
import type { Game, RemovableGameStatus, ScanRoot } from './api/contracts'
import BatchManagementBar from './features/library/BatchManagementBar.vue'
import GameGrid from './features/library/GameGrid.vue'
import LibraryToolbar from './features/library/LibraryToolbar.vue'
import { filterGames } from './features/library/libraryFilters'
import { useLibraryStore } from './features/library/libraryStore'
import MoveSuggestionPanel from './features/library/MoveSuggestionPanel.vue'
import UiScaleControl from './features/preferences/UiScaleControl.vue'
import { applyUiScale, type UiScale } from './features/preferences/uiScale'
import ScanRootDialog from './features/scan-roots/ScanRootDialog.vue'
import ScanRootList from './features/scan-roots/ScanRootList.vue'
import './features/library/library.css'

const bridge = inject(bridgeKey, createBridge())
const store = useLibraryStore(getActivePinia() ?? createPinia())
const { roots, games, error, scanTasks, taskSnapshots, moveSuggestions } = storeToRefs(store)
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
const selectedGameIds = ref<Set<string>>(new Set())
const filteredGames = computed(() => filterGames(games.value, {
  query: store.query,
  status: store.statusFilter,
  engine: store.engineFilter,
}))
const engines = computed(() => [...new Set(games.value.map((game) => game.engineId).filter((value): value is string => Boolean(value)))].sort())
const removableGames = computed(() => games.value.filter(isRemovableGame))
const selectedBatchGames = computed(() => removableGames.value.filter((game) => selectedGameIds.value.has(game.id)))
const selectedInstalledCount = computed(() => selectedBatchGames.value.filter((game) => game.status === 'installed').length)
const selectedMissingCount = computed(() => selectedBatchGames.value.filter((game) => game.status === 'missing').length)
const visibleRemovableGames = computed(() => filteredGames.value.filter(isRemovableGame))

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
  batchMode.value = true
  batchError.value = ''
  batchNotice.value = ''
  selectedGameIds.value = new Set()
}

function exitBatchMode() {
  batchMode.value = false
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
  batchBusy.value = false
  if (!result.ok) {
    if (result.error.code === 'invalid_game_state' || result.error.code === 'game_not_found') {
      await store.load(bridge)
      exitBatchMode()
      batchNotice.value = '游戏状态已经变化，请重新选择。'
      return
    }
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
  applyUiScale(uiScale.value, document.documentElement)
  await store.load(bridge)
  state.value = 'ready'
  await nextTick()
  for (const root of roots.value.filter((item) => item.enabled)) {
    await store.scan(bridge, root.id, 'quick')
  }
}

async function rootSaved() {
  showAddRoot.value = false
  editingRoot.value = null
  await store.load(bridge)
}

async function gameRemoved() {
  await store.load(bridge)
}

async function scan(rootId: string) {
  await store.scan(bridge, rootId, 'full')
}

onMounted(bootstrap)
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

    <section v-if="state === 'connecting'" class="empty-state" aria-live="polite"><h2>正在连接本地数据库…</h2></section>
    <section v-else-if="state === 'failed'" class="empty-state" role="alert"><h2>无法连接本地数据库</h2><p>{{ errorMessage }}</p><button type="button" @click="bootstrap">重试</button></section>

    <template v-else>
      <div v-if="error" class="error-banner" role="alert"><span>{{ error }}</span><button type="button" @click="store.dismissError">关闭</button></div>
      <div class="library-layout">
        <ScanRootList :bridge="bridge" :roots="roots" :scan-tasks="scanTasks" :task-snapshots="taskSnapshots" @scan="scan" @cancel="(id) => store.cancelScan(bridge, id)" @toggle="(root, enabled) => store.updateRoot(bridge, root, enabled)" @edit="editingRoot = $event" @remove="(id) => store.removeRoot(bridge, id)" @remap="(id, path) => store.remapRoot(bridge, id, path)" />
        <section class="library-content">
          <div class="content-heading">
            <h2>我的游戏 <span>{{ games.length }}</span></h2>
            <button v-if="!batchMode && removableGames.length" data-test="enter-batch-mode" class="secondary" type="button" @click="enterBatchMode">批量管理</button>
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
          <MoveSuggestionPanel :suggestions="moveSuggestions" :games="games" @confirm="store.confirmMove(bridge, $event)" />
          <div v-if="games.length === 0" class="empty-state compact"><h2 id="empty-title">还没有添加游戏目录</h2><p>添加一个或多个本地目录后，游戏会显示在这里。</p><button type="button" @click="showAddRoot = true">添加第一个目录</button></div>
          <template v-else>
            <LibraryToolbar v-model:query="store.query" v-model:status="store.statusFilter" v-model:engine="store.engineFilter" :engines="engines" />
            <div v-if="filteredGames.length === 0" class="empty-state compact"><h2>没有符合筛选条件的游戏</h2><p>请调整搜索词或筛选条件。</p></div>
            <GameGrid
              v-else
              :games="filteredGames"
              :bridge="bridge"
              :batch-mode="batchMode"
              :selected-game-ids="selectedGameIds"
              @toggle-selection="toggleBatchGame"
              @updated="store.updateGame"
              @removed="gameRemoved"
            />
          </template>
        </section>
      </div>
      <div v-if="showAddRoot" class="dialog-backdrop" @click.self="showAddRoot = false"><ScanRootDialog :bridge="bridge" @saved="rootSaved" @close="showAddRoot = false" /></div>
      <div v-if="editingRoot" class="dialog-backdrop" @click.self="editingRoot = null"><ScanRootDialog :bridge="bridge" :root="editingRoot" @saved="rootSaved" @close="editingRoot = null" /></div>
    </template>
  </main>
</template>
