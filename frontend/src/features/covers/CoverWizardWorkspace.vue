<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { CoverUpload, CoverWizardSettings, Game, GameSaveScoutBridge } from '../../api/contracts'
import { readClipboardPng } from './coverClipboard'
import CoverCandidateGallery from './CoverCandidateGallery.vue'
import CoverCandidateToolbar from './CoverCandidateToolbar.vue'
import { readDroppedCoverFiles } from './coverDrop'
import CoverWizardQueue from './CoverWizardQueue.vue'
import CoverWizardSettingsPanel from './CoverWizardSettings.vue'
import { useCoverWizardStore } from './coverWizardStore'

const props = defineProps<{
  bridge: GameSaveScoutBridge
  games: Game[]
  settings: CoverWizardSettings
}>()
const emit = defineEmits<{
  updated: [game: Game]
  settingsUpdated: [settings: CoverWizardSettings]
}>()
const store = useCoverWizardStore()
const localSettings = ref({ ...props.settings })
const settingsError = ref('')
const settingsBusy = ref(false)
const launchBusy = ref(false)
const launchMessage = ref('')
const opening = ref(true)
let openingPromise: Promise<void> | null = null
type GalleryHandle = { scrollToTop: () => void }
const gallery = ref<GalleryHandle | null>(null)

const currentGame = computed(() => (
  props.games.find((game) => game.id === store.selectedGameId) ?? null
))
const currentTitle = computed(() => currentGame.value?.title ?? '当前游戏')
const currentVersion = computed(() => currentGame.value?.version ?? null)

onMounted(() => {
  openingPromise = (async () => {
    try {
      await store.open(props.bridge)
    } finally {
      opening.value = false
    }
  })()
})
onBeforeUnmount(() => {
  store.clearPolling()
})

watch(
  () => store.selectedGameId,
  async () => {
    await nextTick()
    gallery.value?.scrollToTop()
  },
  { flush: 'post' },
)

async function selectGame(gameId: string) {
  await store.selectGame(props.bridge, gameId)
}

async function launchCurrentGame() {
  const game = currentGame.value
  if (launchBusy.value || game?.status !== 'installed' || !game.mainExeRelpath) return
  launchBusy.value = true
  launchMessage.value = ''
  try {
    const result = await props.bridge.launch_game({ gameId: game.id })
    launchMessage.value = result.ok ? '游戏已启动' : result.error.message
  } catch {
    launchMessage.value = '启动游戏失败，请稍后重试。'
  } finally {
    launchBusy.value = false
  }
}

async function searchCurrent() {
  if (!store.session || !store.selectedGameId) return
  await store.startSourceTask(
    props.bridge,
    props.bridge.start_cover_vndb_search({
      sessionId: store.session.id,
      gameIds: [store.selectedGameId],
      limit: localSettings.value.coverVndbCandidateLimit,
    }),
  )
}

async function searchAll() {
  if (!store.session) return
  const gameIds = store.session.queue
    .filter((item) => ['pending', 'ready', 'failed'].includes(item.status))
    .map((item) => item.gameId)
  if (!gameIds.length) return
  if (!window.confirm(`将向 VNDB 发送 ${gameIds.length} 个游戏标题，是否继续？`)) return
  await store.startSourceTask(
    props.bridge,
    props.bridge.start_cover_vndb_search({
      sessionId: store.session.id,
      gameIds,
      limit: localSettings.value.coverVndbCandidateLimit,
    }),
  )
}

async function scanShallow() {
  if (!store.session || !store.selectedGameId || !currentGame.value?.installPath) return
  await store.startSourceTask(
    props.bridge,
    props.bridge.start_cover_shallow_scan({
      sessionId: store.session.id,
      gameId: store.selectedGameId,
      limit: localSettings.value.coverLocalScanCandidateLimit,
      depth: localSettings.value.coverLocalScanDepth,
    }),
  )
}

async function importDirectory() {
  if (!store.session) return
  const selected = await props.bridge.choose_directory()
  if (!selected.ok) {
    store.sourceError = selected.error.message
    return
  }
  if (!selected.data) return
  await store.startSourceTask(
    props.bridge,
    props.bridge.start_cover_directory_import({
      sessionId: store.session.id,
      selectedPath: selected.data,
    }),
  )
}

async function addFiles(files: FileList | File[]) {
  try {
    const uploads = await readDroppedCoverFiles(files)
    await store.addUploads(props.bridge, uploads, 'drop')
  } catch (error) {
    store.sourceError = error instanceof Error ? error.message : '无法读取拖入的图片。'
  }
}

async function paste() {
  try {
    const dataBase64 = await readClipboardPng(navigator.clipboard)
    const upload: CoverUpload = {
      fileName: 'clipboard.png',
      contentType: 'image/png',
      dataBase64,
    }
    await store.addUploads(props.bridge, [upload], 'clipboard')
  } catch (error) {
    store.sourceError = error instanceof Error ? error.message : '无法读取剪贴板图片。'
  }
}

async function saveSettings(settings: CoverWizardSettings) {
  settingsBusy.value = true
  settingsError.value = ''
  try {
    const result = await props.bridge.set_cover_wizard_settings(settings)
    if (!result.ok) {
      settingsError.value = result.error.message
      return
    }
    localSettings.value = result.data
    emit('settingsUpdated', result.data)
  } catch {
    settingsError.value = '保存封面设置失败，请稍后重试。'
  } finally {
    settingsBusy.value = false
  }
}

async function adopt() {
  const game = await store.adopt(props.bridge)
  if (game) emit('updated', game)
}

async function requestClose(): Promise<boolean> {
  await openingPromise
  if (!store.session) {
    store.clearPolling()
    return true
  }
  if (store.activeTaskId && !window.confirm('退出将取消正在进行的搜索，并清理未采用候选。是否继续？')) {
    return false
  }
  return store.requestClose(props.bridge)
}

defineExpose({ requestClose })
</script>

<template>
  <section
    class="cover-wizard-workspace"
    data-test="cover-wizard-workspace"
    aria-labelledby="cover-wizard-title"
    @dragover.prevent
    @drop.prevent="addFiles($event.dataTransfer?.files ?? [])"
  >
    <header class="cover-wizard-header">
      <div>
        <p>批量封面</p>
        <h1 id="cover-wizard-title">为游戏挑选封面</h1>
      </div>
    </header>
    <div v-if="opening" class="cover-gallery-empty">正在建立封面会话…</div>
    <div v-else-if="!store.session" class="cover-gallery-empty" role="alert">
      {{ store.error || '无法建立封面会话。' }}
    </div>
    <div v-else class="cover-wizard-layout">
      <CoverWizardQueue
        :items="store.session.queue"
        :selected-game-id="store.selectedGameId"
        :include-existing="store.session.includeExisting"
        @select="selectGame"
        @update:include-existing="store.setIncludeExisting(props.bridge, $event)"
      />
      <main class="cover-wizard-review">
        <div class="cover-review-heading">
          <div>
            <p>当前游戏</p>
            <div class="cover-review-title-row">
              <h2>{{ currentTitle }}</h2>
              <span v-if="currentVersion" class="cover-review-version">{{ currentVersion }}</span>
              <button
                data-test="cover-launch-current"
                class="secondary cover-review-launch"
                type="button"
                :disabled="launchBusy || currentGame?.status !== 'installed' || !currentGame?.mainExeRelpath"
                @click="launchCurrentGame"
              >{{ launchBusy ? '正在启动…' : '启动游戏' }}</button>
            </div>
            <p
              v-if="launchMessage"
              data-test="cover-launch-message"
              class="cover-launch-message status-message"
              aria-live="polite"
            >{{ launchMessage }}</p>
          </div>
          <CoverWizardSettingsPanel
            :settings="localSettings"
            :busy="settingsBusy"
            :error="settingsError"
            @save="saveSettings"
          />
        </div>
        <CoverCandidateToolbar
          :game="currentGame"
          :settings="localSettings"
          :source-active="Boolean(store.activeTaskId)"
          :task="store.taskSnapshot"
          @vndb-current="searchCurrent"
          @vndb-all="searchAll"
          @shallow="scanShallow"
          @directory="importDirectory"
          @paste="paste"
          @files="addFiles"
        />
        <CoverCandidateGallery
          ref="gallery"
          :candidates="store.candidates"
          :selected-id="store.selectedCandidateId"
          :game-title="currentTitle"
          :loading="Boolean(store.activeTaskId) && store.candidates.length === 0"
          :error="store.sourceError"
          @select="store.selectedCandidateId = $event"
        />
        <p v-if="store.error" class="cover-source-error" role="alert">{{ store.error }}</p>
        <footer class="cover-review-actions">
          <button type="button" class="secondary" :disabled="!store.selectedGameId" @click="store.skip(props.bridge)">跳过并下一个</button>
          <button type="button" :disabled="!store.selectedCandidateId" @click="adopt">采用并下一个</button>
        </footer>
      </main>
    </div>
  </section>
</template>
