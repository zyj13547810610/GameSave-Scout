<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { computed, ref, watch } from 'vue'
import type { GameShelfBridge, GuidedSaveDiscovery } from '../../api/contracts'
import { confidenceLabel, saveKindLabel } from './saveLocationLabels'
import { useGuidedSaveStore } from './guidedSaveStore'

const props = defineProps<{ bridge: GameShelfBridge }>()
const emit = defineEmits<{ accepted: [] }>()
const store = useGuidedSaveStore()
const { discoveries, error, session } = storeToRefs(store)
const selected = ref(new Set<string>())
const message = ref('')
const loading = ref(false)
const groups = computed(() => [
  { id: 'high', label: '高可信候选', items: discoveries.value.filter((item) => item.kind !== 'registry' && item.confidence >= 0.85) },
  { id: 'medium', label: '中可信候选', items: discoveries.value.filter((item) => item.kind !== 'registry' && item.confidence >= 0.6 && item.confidence < 0.85) },
  { id: 'low', label: '低可信候选', items: discoveries.value.filter((item) => item.kind !== 'registry' && item.confidence < 0.6) },
  { id: 'registry', label: '注册表候选', items: discoveries.value.filter((item) => item.kind === 'registry') },
].filter((group) => group.items.length))

watch(discoveries, (items) => {
  selected.value = new Set(items.filter(isSafePreselection).map((item) => item.id))
}, { immediate: true })

function isSafePreselection(item: GuidedSaveDiscovery): boolean {
  return item.preselected
    && item.kind !== 'registry'
    && item.markOffsetMs !== null
    && !item.affectedByOverflow
    && !item.affectedByTruncation
}

function toggle(id: string, checked: boolean) {
  const next = new Set(selected.value)
  if (checked) next.add(id)
  else next.delete(id)
  selected.value = next
}

async function accept() {
  const ids = [...selected.value]
  if (!ids.length) return void (message.value = '请先选择至少一个候选。')
  const hasRegistry = discoveries.value.some(
    (item) => selected.value.has(item.id) && item.kind === 'registry',
  )
  if (hasRegistry && !window.confirm('所选内容包含注册表位置。确认将它加入游戏的存档位置吗？')) return
  loading.value = true
  const accepted = await store.accept(props.bridge, ids, hasRegistry)
  loading.value = false
  if (accepted) {
    selected.value = new Set()
    emit('accepted')
  }
}

async function discard() {
  if (!window.confirm('丢弃本次尚未接受的寻找结果吗？不会删除任何存档文件。')) return
  loading.value = true
  await store.discard(props.bridge)
  loading.value = false
}
</script>

<template>
  <section class="guided-discoveries">
    <div class="save-location-heading"><h4>引导式寻找结果</h4></div>
    <p v-if="session?.overflowedScopes.length" class="warning-text">
      部分监控事件曾溢出，已仅对受影响范围执行受限补扫。
    </p>
    <p v-if="session?.truncatedScopes.length" class="warning-text">
      部分监控范围的结果不完整，请结合候选证据人工确认。
    </p>
    <p v-if="discoveries.length === 0" class="empty-save-message">
      本次没有发现可审核的位置。可以手动添加位置，或使用下方的静态“查找存档”。
    </p>
    <details v-for="group in groups" :key="group.id" class="guided-discovery-group" :open="group.id !== 'low'">
      <summary>{{ group.label }}（{{ group.items.length }}）</summary>
      <label v-for="item in group.items" :key="item.id" class="save-suggestion-card">
        <input
          :data-test="`guided-discovery-${item.id}`"
          type="checkbox"
          :checked="selected.has(item.id)"
          @change="toggle(item.id, ($event.target as HTMLInputElement).checked)"
        >
        <span class="suggestion-content">
          <span class="save-location-title"><strong>{{ saveKindLabel(item.kind) }}</strong><span>{{ confidenceLabel(item.confidence) }}</span></span>
          <span class="save-display-path">{{ item.displayPath }}</span>
          <small v-if="item.markOffsetMs !== null">距保存标记 {{ item.markOffsetMs }} 毫秒</small>
          <small v-else class="warning-text">没有保存标记，按整个会话分析</small>
          <small v-if="item.affectedByOverflow" class="warning-text">监控事件曾溢出，已执行受限补扫</small>
          <small v-if="item.affectedByTruncation" class="warning-text">补扫达到资源上限，结果可能不完整</small>
          <details>
            <summary>证据与代表文件</summary>
            <ul><li v-for="entry in item.evidence" :key="entry">{{ entry }}</li></ul>
            <code v-for="file in item.representativeFiles" :key="file">{{ file }}</code>
          </details>
        </span>
      </label>
    </details>
    <div v-if="discoveries.length" class="compact-actions">
      <button data-test="accept-guided-discoveries" type="button" :disabled="loading" @click="accept">接受所选位置</button>
      <button data-test="discard-guided-discoveries" type="button" class="danger" :disabled="loading" @click="discard">丢弃结果</button>
    </div>
    <p v-if="message || error" class="status-message" role="alert">{{ message || error }}</p>
  </section>
</template>
