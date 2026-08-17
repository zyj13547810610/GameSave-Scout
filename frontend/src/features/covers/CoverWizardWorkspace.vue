<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { CoverUpload, CoverWizardSettings, Game, GameShelfBridge } from '../../api/contracts'
import { readClipboardPng } from './coverClipboard'
import CoverCandidateGallery from './CoverCandidateGallery.vue'
import CoverCandidateToolbar from './CoverCandidateToolbar.vue'
import { readDroppedCoverFiles } from './coverDrop'
import CoverWizardQueue from './CoverWizardQueue.vue'
import CoverWizardSettingsPanel from './CoverWizardSettings.vue'
import { useCoverWizardStore } from './coverWizardStore'

const props = defineProps<{
  bridge: GameShelfBridge
  games: Game[]
  settings: CoverWizardSettings
}>()
const emit = defineEmits<{ updated: [game: Game]; close: [] }>()
const store = useCoverWizardStore()
const root = ref<HTMLElement | null>(null)
const localSettings = ref({ ...props.settings })
const settingsError = ref('')
const settingsBusy = ref(false)
const opening = ref(true)

const currentGame = computed(() => (
  props.games.find((game) => game.id === store.selectedGameId) ?? null
))
const currentTitle = computed(() => currentGame.value?.title ?? '当前游戏')

onMounted(async () => {
  await store.open(props.bridge)
  opening.value = false
  await nextTick()
  root.value?.querySelector<HTMLElement>('[data-autofocus]')?.focus()
})
onBeforeUnmount(() => store.clearPolling())

async function selectGame(gameId: string) {
  await store.selectGame(props.bridge, gameId)
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
  const result = await props.bridge.set_cover_wizard_settings(settings)
  settingsBusy.value = false
  if (!result.ok) {
    settingsError.value = result.error.message
    return
  }
  localSettings.value = result.data
}

async function adopt() {
  const game = await store.adopt(props.bridge)
  if (game) emit('updated', game)
}

async function requestClose() {
  if (store.activeTaskId && !window.confirm('退出将取消正在进行的搜索，并清理未采用候选。是否继续？')) return
  if (await store.requestClose(props.bridge)) emit('close')
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    void requestClose()
    return
  }
  if (event.key !== 'Tab' || !root.value) return
  const focusable = Array.from(root.value.querySelectorAll<HTMLElement>(
    'button:not(:disabled), input:not(:disabled), select:not(:disabled), summary, [tabindex]:not([tabindex="-1"])',
  )).filter((item) => item.offsetParent !== null)
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault(); last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault(); first.focus()
  }
}
</script>

<template>
  <section
    ref="root"
    class="cover-wizard-workspace"
    data-test="cover-wizard-workspace"
    role="dialog"
    aria-modal="true"
    aria-labelledby="cover-wizard-title"
    @keydown="onKeydown"
    @dragover.prevent
    @drop.prevent="addFiles($event.dataTransfer?.files ?? [])"
  >
    <header class="cover-wizard-header">
      <div>
        <p>批量封面</p>
        <h1 id="cover-wizard-title">为游戏挑选封面</h1>
      </div>
      <button data-autofocus type="button" class="secondary" @click="requestClose">返回游戏库</button>
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
            <h2>{{ currentTitle }}</h2>
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
