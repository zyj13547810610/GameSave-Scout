<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { GameShelfBridge, SaveLocation, SaveSuggestion } from '../../api/contracts'
import { confidenceLabel, saveKindLabel } from './saveLocationLabels'

const props = defineProps<{
  gameId: string
  bridge: GameShelfBridge
  suggestions?: SaveSuggestion[]
}>()
const emit = defineEmits<{ accepted: [locations: SaveLocation[]] }>()

const items = ref<SaveSuggestion[]>(props.suggestions ? [...props.suggestions] : [])
const selected = ref(new Set<string>())
const loading = ref(false)
const message = ref('')
const hasSearched = ref(props.suggestions !== undefined)

const groups = computed(() => [
  {
    id: 'found',
    label: `已找到（${items.value.filter((item) => item.availability === 'found').length}）`,
    items: items.value.filter((item) => item.availability === 'found'),
  },
  {
    id: 'predicted',
    label: `可能路径 / 未发现（${items.value.filter((item) => item.availability === 'predicted').length}）`,
    items: items.value.filter((item) => item.availability === 'predicted'),
  },
].filter((group) => group.items.length > 0))

watch(() => props.suggestions, (suggestions) => {
  if (suggestions) {
    hasSearched.value = true
    setItems(suggestions)
  }
})

onMounted(() => {
  if (props.suggestions !== undefined) setItems(props.suggestions)
})

function setItems(suggestions: SaveSuggestion[]) {
  items.value = [...suggestions]
  selected.value = new Set(
    suggestions
      .filter((item) => (
        item.preselected
        && item.availability === 'found'
        && item.kind !== 'registry'
      ))
      .map((item) => item.suggestionId),
  )
}

async function refresh() {
  hasSearched.value = true
  loading.value = true
  message.value = ''
  const result = await props.bridge.suggest_save_locations({ gameId: props.gameId })
  loading.value = false
  if (!result.ok) return void (message.value = result.error.message)
  setItems(result.data)
}

function toggle(suggestionId: string, checked: boolean) {
  const next = new Set(selected.value)
  if (checked) next.add(suggestionId)
  else next.delete(suggestionId)
  selected.value = next
}

async function acceptSelected() {
  const suggestionIds = [...selected.value]
  if (suggestionIds.length === 0) {
    message.value = '请先选择至少一个建议。'
    return
  }
  const hasRegistry = items.value.some(
    (item) => selected.value.has(item.suggestionId) && item.kind === 'registry',
  )
  if (hasRegistry && !window.confirm('所选内容包含注册表位置。确认将它加入游戏的存档位置吗？')) return

  loading.value = true
  const result = await props.bridge.accept_save_suggestions({
    gameId: props.gameId,
    suggestionIds,
    confirmRegistry: hasRegistry,
  })
  loading.value = false
  if (!result.ok) return void (message.value = result.error.message)
  items.value = items.value.filter((item) => !selected.value.has(item.suggestionId))
  selected.value = new Set()
  message.value = `已接受 ${result.data.length} 个存档位置。`
  emit('accepted', result.data)
}

function categoryLabel(category: SaveSuggestion['category']): string {
  return { save: '存档', config: '配置', other: '其他' }[category]
}

function evidenceSourceLabel(source: SaveSuggestion['sourceEvidence'][number]['source']): string {
  return {
    user: '用户规则',
    builtin: '内置规则',
    ludusavi: 'Ludusavi',
    engine: '引擎规则',
  }[source]
}

function suggestionGroupLabel(group: SaveSuggestion['group']): string {
  return { exact: '高可信', possible: '可能', experimental: '实验性' }[group]
}
</script>

<template>
  <section class="save-suggestions">
    <div class="save-location-heading">
      <h4>查找存档位置</h4>
      <button
        data-test="find-save-suggestions"
        type="button"
        class="secondary"
        :disabled="loading"
        @click="refresh"
      >
        {{ hasSearched ? '重新查找' : '查找存档' }}
      </button>
    </div>

    <p v-if="!hasSearched" class="empty-save-message">
      点击后才会检查用户规则、内置规则、Ludusavi 和引擎提示。
    </p>
    <p v-else-if="!loading && items.length === 0" class="empty-save-message">
      暂未发现新的存档位置。
    </p>
    <component
      :is="group.id === 'predicted' ? 'details' : 'section'"
      v-for="group in groups"
      :key="group.id"
      class="suggestion-group"
      :data-test="group.id === 'predicted' ? 'predicted-group' : 'found-group'"
    >
      <summary v-if="group.id === 'predicted'">{{ group.label }}</summary>
      <h5 v-else>{{ group.label }}</h5>
      <label v-for="item in group.items" :key="item.suggestionId" class="save-suggestion-card">
        <input
          :data-test="`suggestion-${item.suggestionId}`"
          type="checkbox"
          :checked="selected.has(item.suggestionId)"
          @change="toggle(item.suggestionId, ($event.target as HTMLInputElement).checked)"
        >
        <span class="suggestion-content">
          <span class="save-location-title">
            <strong>{{ saveKindLabel(item.kind) }}</strong>
            <span>{{ categoryLabel(item.category) }}</span>
            <span>{{ confidenceLabel(item.confidence) }}</span>
            <span>{{ suggestionGroupLabel(item.group) }}</span>
          </span>
          <span class="save-display-path">{{ item.displayPath }}</span>
          <small v-for="entry in item.sourceEvidence" :key="`${entry.source}:${entry.detail}`">
            {{ evidenceSourceLabel(entry.source) }}：{{ entry.detail }}
          </small>
          <details>
            <summary>路径模板</summary>
            <code>{{ item.pathTemplate }}</code>
          </details>
        </span>
      </label>
    </component>

    <button
      v-if="items.length"
      data-test="accept-selected"
      type="button"
      :disabled="loading"
      @click="acceptSelected"
    >
      接受所选位置
    </button>
    <p class="status-message" aria-live="polite">{{ loading ? '正在查找存档位置……' : message }}</p>
  </section>
</template>
