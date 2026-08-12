<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { GameShelfBridge, SaveLocation } from '../../api/contracts'
import AddSaveLocationDialog from './AddSaveLocationDialog.vue'
import LudusaviSettings from './LudusaviSettings.vue'
import { confidenceLabel, saveKindLabel, saveSourceLabel } from './saveLocationLabels'
import SaveSuggestionList from './SaveSuggestionList.vue'

const props = defineProps<{
  gameId: string
  bridge: GameShelfBridge
  locations?: SaveLocation[]
}>()
const items = ref<SaveLocation[]>(props.locations ? [...props.locations] : [])
const loading = ref(false)
const showAdd = ref(false)
const message = ref('')
const visibleItems = computed(() => items.value.filter((item) => item.enabled))

watch(() => props.locations, (locations) => {
  if (locations) items.value = [...locations]
})

onMounted(() => {
  if (props.locations === undefined) void refresh()
})

async function refresh() {
  loading.value = true
  message.value = ''
  const result = await props.bridge.list_save_locations({ gameId: props.gameId })
  loading.value = false
  if (!result.ok) return void (message.value = result.error.message)
  items.value = result.data
}

async function verify() {
  loading.value = true
  const result = await props.bridge.verify_save_locations({ gameId: props.gameId })
  loading.value = false
  if (!result.ok) return void (message.value = result.error.message)
  items.value = result.data
  message.value = '验证完成'
}

async function open(location: SaveLocation) {
  if (!location.confirmed && !window.confirm('此路径尚未确认，仍要打开吗？')) return
  const result = await props.bridge.open_save_location({ locationId: location.id })
  if (!result.ok) message.value = result.error.message
}

async function remove(location: SaveLocation) {
  if (!window.confirm(`确定移除存档位置“${location.displayPath}”吗？这不会删除任何存档文件。`)) return
  const result = await props.bridge.remove_save_location({ locationId: location.id })
  if (!result.ok) return void (message.value = result.error.message)
  items.value = items.value.filter((item) => item.id !== location.id)
  message.value = '存档位置已移除，文件未被删除。'
}

async function added() {
  showAdd.value = false
  await refresh()
}

function verifiedLabel(value: string | null): string {
  return value ? `最近验证：${new Date(value).toLocaleString()}` : '尚未验证'
}
</script>

<template>
  <section class="save-locations">
    <div class="save-location-heading">
      <h3>存档位置</h3>
      <div class="compact-actions">
        <button type="button" :disabled="loading" @click="showAdd = true">手动添加</button>
        <button type="button" class="secondary" :disabled="loading" @click="verify">验证</button>
      </div>
    </div>

    <p v-if="!loading && visibleItems.length === 0" class="empty-save-message">还没有已确认的存档位置。</p>
    <article v-for="location in visibleItems" :key="location.id" data-test="save-location" class="save-location-card">
      <div class="save-location-title">
        <strong>{{ saveKindLabel(location.kind) }}</strong>
        <span>{{ saveSourceLabel(location.source) }}</span>
        <span>{{ location.confirmed ? '已确认' : '建议' }}</span>
      </div>
      <p class="save-display-path">{{ location.displayPath }}</p>
      <p v-if="location.exists === false" class="save-missing">当前位置不存在</p>
      <p v-else-if="location.kind === 'glob' && location.matchCount !== null">
        匹配 {{ location.matchCount }} 项{{ location.matchesTruncated ? '以上' : '' }}
      </p>
      <p class="save-location-meta">{{ confidenceLabel(location.confidence) }} · {{ verifiedLabel(location.lastVerifiedAt) }}</p>
      <div class="compact-actions">
        <button type="button" @click="open(location)">打开</button>
        <button data-test="remove-save-location" type="button" class="danger" @click="remove(location)">移除</button>
      </div>
      <details>
        <summary>高级信息</summary>
        <code>{{ location.pathTemplate }}</code>
        <ul v-if="location.evidence.length">
          <li v-for="entry in location.evidence" :key="entry">{{ entry }}</li>
        </ul>
      </details>
    </article>

    <p class="status-message" aria-live="polite">{{ loading ? '正在读取存档位置…' : message }}</p>
    <SaveSuggestionList :game-id="gameId" :bridge="bridge" @accepted="refresh" />
    <details class="ludusavi-settings-details">
      <summary>存档规则设置</summary>
      <LudusaviSettings :bridge="bridge" />
    </details>
    <AddSaveLocationDialog
      v-if="showAdd"
      :game-id="gameId"
      :bridge="bridge"
      @close="showAdd = false"
      @saved="added"
    />
  </section>
</template>
