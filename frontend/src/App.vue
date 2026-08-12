<script setup lang="ts">
import { createPinia, getActivePinia, storeToRefs } from 'pinia'
import { computed, inject, nextTick, onMounted, ref } from 'vue'
import { bridgeKey, createBridge } from './api/bridge'
import GameGrid from './features/library/GameGrid.vue'
import LibraryToolbar from './features/library/LibraryToolbar.vue'
import { filterGames } from './features/library/libraryFilters'
import { useLibraryStore } from './features/library/libraryStore'
import MoveSuggestionPanel from './features/library/MoveSuggestionPanel.vue'
import ScanRootDialog from './features/scan-roots/ScanRootDialog.vue'
import ScanRootList from './features/scan-roots/ScanRootList.vue'
import './features/library/library.css'

const bridge = inject(bridgeKey, createBridge())
const store = useLibraryStore(getActivePinia() ?? createPinia())
const { roots, games, error, scanTasks, moveSuggestions } = storeToRefs(store)
const state = ref<'connecting' | 'ready' | 'failed'>('connecting')
const errorMessage = ref('')
const showAddRoot = ref(false)
const filteredGames = computed(() => filterGames(games.value, {
  query: store.query,
  status: store.statusFilter,
  engine: store.engineFilter,
}))
const engines = computed(() => [...new Set(games.value.map((game) => game.engineId).filter((value): value is string => Boolean(value)))].sort())

async function bootstrap() {
  state.value = 'connecting'
  const result = await bridge.bootstrap()
  if (!result.ok) {
    errorMessage.value = result.error.message
    state.value = 'failed'
    return
  }
  await store.load(bridge)
  state.value = 'ready'
  await nextTick()
  for (const root of roots.value.filter((item) => item.enabled)) {
    await store.scan(bridge, root.id, 'quick')
  }
}

async function rootSaved() {
  showAddRoot.value = false
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
      <button v-if="state === 'ready'" type="button" @click="showAddRoot = true">＋ 添加游戏目录</button>
    </header>

    <section v-if="state === 'connecting'" class="empty-state" aria-live="polite"><h2>正在连接本地数据库…</h2></section>
    <section v-else-if="state === 'failed'" class="empty-state" role="alert"><h2>无法连接本地数据库</h2><p>{{ errorMessage }}</p><button type="button" @click="bootstrap">重试</button></section>

    <template v-else>
      <div v-if="error" class="error-banner" role="alert"><span>{{ error }}</span><button type="button" @click="store.dismissError">关闭</button></div>
      <div class="library-layout">
        <ScanRootList :bridge="bridge" :roots="roots" :scan-tasks="scanTasks" @scan="scan" @cancel="(id) => store.cancelScan(bridge, id)" @toggle="(root, enabled) => store.updateRoot(bridge, root, enabled)" @remove="(id) => store.removeRoot(bridge, id)" @remap="(id, path) => store.remapRoot(bridge, id, path)" />
        <section class="library-content">
          <div class="content-heading"><h2>我的游戏 <span>{{ games.length }}</span></h2></div>
          <MoveSuggestionPanel :suggestions="moveSuggestions" :games="games" @confirm="store.confirmMove(bridge, $event)" />
          <div v-if="games.length === 0" class="empty-state compact"><h2 id="empty-title">还没有添加游戏目录</h2><p>添加一个或多个本地目录后，游戏会显示在这里。</p><button type="button" @click="showAddRoot = true">添加第一个目录</button></div>
          <template v-else>
            <LibraryToolbar v-model:query="store.query" v-model:status="store.statusFilter" v-model:engine="store.engineFilter" :engines="engines" />
            <div v-if="filteredGames.length === 0" class="empty-state compact"><h2>没有符合筛选条件的游戏</h2><p>请调整搜索词或筛选条件。</p></div>
            <GameGrid v-else :games="filteredGames" :bridge="bridge" @updated="store.updateGame" />
          </template>
        </section>
      </div>
      <div v-if="showAddRoot" class="dialog-backdrop" @click.self="showAddRoot = false"><ScanRootDialog :bridge="bridge" @saved="rootSaved" @close="showAddRoot = false" /></div>
    </template>
  </main>
</template>
