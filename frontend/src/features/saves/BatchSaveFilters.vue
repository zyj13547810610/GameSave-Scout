<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { computed, onBeforeUnmount, watch } from 'vue'
import type { GameShelfBridge } from '../../api/contracts'
import { useBatchSaveStore } from './batchSaveStore'

const props = defineProps<{ bridge: GameShelfBridge }>()
const store = useBatchSaveStore()
const { filters, total, loading, actionBusy } = storeToRefs(store)
const pageStart = computed(() => total.value === 0 ? 0 : filters.value.offset + 1)
const pageEnd = computed(() => Math.min(total.value, filters.value.offset + filters.value.limit))
let keywordTimer: number | null = null

async function applyFilters() {
  filters.value.offset = 0
  await store.loadPage(props.bridge)
}

function clearKeywordTimer() {
  if (keywordTimer !== null) window.clearTimeout(keywordTimer)
  keywordTimer = null
}

async function applyKeywordNow() {
  clearKeywordTimer()
  await applyFilters()
}

watch(
  () => [filters.value.status, filters.value.confidence, filters.value.source],
  () => void applyFilters(),
)

watch(
  () => filters.value.keyword,
  () => {
    clearKeywordTimer()
    keywordTimer = window.setTimeout(() => {
      keywordTimer = null
      void applyFilters()
    }, 300)
  },
)

onBeforeUnmount(clearKeywordTimer)

async function page(direction: -1 | 1) {
  filters.value.offset = Math.max(0, filters.value.offset + direction * filters.value.limit)
  await store.loadPage(props.bridge)
}
</script>

<template>
  <form class="batch-save-filters" data-test="batch-filter-form" @submit.prevent="applyKeywordNow">
    <input v-model="filters.keyword" data-test="batch-keyword-filter" type="search" aria-label="搜索存档候选" placeholder="搜索标题、产品编号或路径" />
    <select v-model="filters.status" data-test="batch-status-filter" aria-label="候选状态">
      <option value="all">全部</option><option value="pending">待处理</option>
      <option value="installed">已安装游戏</option><option value="missing">本体失效</option>
      <option value="unknown">未关联游戏</option><option value="recorded">已记录</option>
      <option value="ignored">已忽略</option><option value="unavailable">不可用</option>
    </select>
    <select v-model="filters.confidence" data-test="batch-confidence-filter" aria-label="可信度">
      <option value="all">全部可信度</option><option value="high">高可信</option>
      <option value="medium">中可信</option><option value="low">低可信</option>
    </select>
    <select v-model="filters.source" data-test="batch-source-filter" aria-label="候选来源">
      <option value="all">全部来源</option><option value="recorded">已记录位置</option>
      <option value="custom">自定义清单</option><option value="builtin">内置规则</option>
      <option value="ludusavi">Ludusavi</option>
      <option value="engine">引擎提示</option><option value="bounded_scan">受限扫描</option>
      <option value="registry">注册表规则</option>
    </select>
    <button data-test="select-current-batch-results" type="button" class="secondary" :disabled="loading || actionBusy || total === 0" @click="store.selectCurrentFiltered(bridge)">全选当前可处理结果</button>
    <div class="batch-pagination">
      <span>{{ pageStart }}–{{ pageEnd }} / {{ total }}</span>
      <button data-test="batch-prev-page" type="button" class="secondary" :disabled="loading || filters.offset === 0" @click="page(-1)">上一页</button>
      <button data-test="batch-next-page" type="button" class="secondary" :disabled="loading || filters.offset + filters.limit >= total" @click="page(1)">下一页</button>
    </div>
  </form>
</template>
