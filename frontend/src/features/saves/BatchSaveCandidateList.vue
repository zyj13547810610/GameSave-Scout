<script setup lang="ts">
import { computed, ref } from 'vue'
import type { BatchSaveCandidate, Game, GameSaveScoutBridge } from '../../api/contracts'
import BatchSaveEvidence from './BatchSaveEvidence.vue'

const props = defineProps<{
  bridge: GameSaveScoutBridge
  candidates: BatchSaveCandidate[]
  games: Game[]
  selectedIds: Set<string>
}>()
const emit = defineEmits<{
  toggle: [candidateId: string]
  inspect: [candidate: BatchSaveCandidate]
  accept: [candidate: BatchSaveCandidate]
  associate: [candidate: BatchSaveCandidate]
  saveOnly: [candidate: BatchSaveCandidate]
  ignore: [candidate: BatchSaveCandidate]
  restore: [candidate: BatchSaveCandidate]
  rollbackSaveOnly: [candidate: BatchSaveCandidate]
}>()
const actionError = ref('')
const grouped = computed(() => {
  const groups = new Map<string, BatchSaveCandidate[]>()
  for (const candidate of props.candidates) {
    const key = candidate.strongGroupKey ?? `candidate:${candidate.id}`
    groups.set(key, [...(groups.get(key) ?? []), candidate])
  }
  return [...groups.entries()].map(([key, items]) => ({ key, items }))
})
const gamesById = computed(() => new Map(props.games.map((game) => [game.id, game])))
const targetId = (candidate: BatchSaveCandidate) => (
  candidate.reviewGameId
  ?? (candidate.confidence === 'high' ? candidate.suggestedGameId : null)
)
const targetTitle = (candidate: BatchSaveCandidate) => {
  const id = targetId(candidate)
  return id ? gamesById.value.get(id)?.title ?? candidate.suggestedTitle : candidate.suggestedTitle
}
const selectable = (candidate: BatchSaveCandidate) => (
  candidate.reviewStatus !== 'recorded' && candidate.reviewStatus !== 'save_only'
)

async function openCandidate(candidate: BatchSaveCandidate) {
  actionError.value = ''
  const result = await props.bridge.open_batch_save_candidate({ candidateId: candidate.id })
  if (!result.ok) actionError.value = result.error.message
}

async function copyPath(candidate: BatchSaveCandidate) {
  actionError.value = ''
  try {
    await navigator.clipboard?.writeText(candidate.displayPath)
  } catch {
    actionError.value = '复制路径失败。'
  }
}

async function lookup(candidate: BatchSaveCandidate, provider: 'vndb' | 'dlsite' | '2dfan') {
  actionError.value = ''
  if (candidate.lookupQuery) {
    try {
      await navigator.clipboard?.writeText(candidate.lookupQuery)
    } catch {
      // Browser opening remains useful even if clipboard access is unavailable.
    }
  }
  const result = await props.bridge.open_batch_save_lookup({ candidateId: candidate.id, provider })
  if (!result.ok) actionError.value = result.error.message
}

const classificationLabel = (candidate: BatchSaveCandidate) => ({
  installed: '已安装游戏', missing: '可能的孤立存档', unknown: '未关联游戏',
}[candidate.classification])
const reviewLabel = (candidate: BatchSaveCandidate) => ({
  pending: '待处理', recorded: '已记录', ignored: '已忽略', save_only: '仅存档卡片',
}[candidate.reviewStatus])
</script>

<template>
  <div class="batch-candidate-groups">
    <p v-if="actionError" class="inline-error" role="alert">{{ actionError }}</p>
    <section v-for="group in grouped" :key="group.key" class="batch-candidate-group">
      <header v-if="group.items.length > 1"><strong>{{ targetTitle(group.items[0]) || '同一候选组' }}</strong><span>{{ group.items.length }} 个位置</span></header>
      <article
        v-for="candidate in group.items"
        :key="candidate.id"
        class="batch-candidate-card"
        :class="{ selected: selectedIds.has(candidate.id) }"
        :data-test="`batch-candidate-${candidate.id}`"
        @click="emit('inspect', candidate)"
      >
        <input
          :data-test="`select-${candidate.id}`"
          type="checkbox"
          :checked="selectedIds.has(candidate.id)"
          :disabled="!selectable(candidate)"
          :aria-label="`选择 ${targetTitle(candidate) || '未知游戏'} 的候选`"
          @click.stop
          @change="emit('toggle', candidate.id)"
        />
        <div class="batch-candidate-main">
          <div class="batch-candidate-title">
            <strong>{{ targetTitle(candidate) || '未知游戏' }}</strong>
            <span>{{ classificationLabel(candidate) }}</span><span>{{ reviewLabel(candidate) }}</span>
            <span v-if="candidate.confidence === 'high' && candidate.suggestedGameId && !candidate.reviewGameId">建议目标</span>
          </div>
          <code class="batch-candidate-path">{{ candidate.displayPath }}</code>
          <div class="batch-candidate-tags">
            <span>{{ candidate.kind }}</span><span>{{ candidate.confidence }}</span>
            <span v-for="source in candidate.sources" :key="source">{{ source }}</span>
          </div>
          <p v-if="candidate.evidence[0]">{{ candidate.evidence[0] }}</p>
          <div class="batch-candidate-actions" @click.stop>
            <button v-if="candidate.reviewStatus === 'pending' && candidate.availability === 'available' && targetId(candidate)" type="button" @click="emit('accept', candidate)">添加</button>
            <button v-if="candidate.availability === 'available' && ['pending', 'ignored'].includes(candidate.reviewStatus)" type="button" class="secondary" @click="emit('associate', candidate)">调整关联</button>
            <button v-if="candidate.reviewStatus === 'pending' && candidate.availability === 'available'" type="button" class="secondary" @click="emit('saveOnly', candidate)">创建仅存档卡片</button>
            <button v-if="candidate.reviewStatus === 'pending'" type="button" class="secondary" @click="emit('ignore', candidate)">忽略</button>
            <button v-if="candidate.reviewStatus === 'ignored'" type="button" class="secondary" @click="emit('restore', candidate)">恢复</button>
            <button
              v-if="candidate.reviewStatus === 'save_only'"
              :data-test="`rollback-save-only-${candidate.id}`"
              type="button"
              class="danger"
              @click="emit('rollbackSaveOnly', candidate)"
            >撤销创建</button>
            <button v-if="candidate.kind !== 'registry' && candidate.availability === 'available'" type="button" class="secondary" @click="openCandidate(candidate)">打开位置</button>
            <button type="button" class="secondary" @click="copyPath(candidate)">复制路径</button>
            <template v-if="candidate.lookupQuery">
              <button :data-test="`lookup-vndb-${candidate.id}`" type="button" class="secondary" @click="lookup(candidate, 'vndb')">VNDB</button>
              <button :data-test="`lookup-dlsite-${candidate.id}`" type="button" class="secondary" @click="lookup(candidate, 'dlsite')">DLsite</button>
              <button :data-test="`lookup-2dfan-${candidate.id}`" type="button" class="secondary" @click="lookup(candidate, '2dfan')">2DFan</button>
            </template>
          </div>
          <details class="batch-inline-evidence"><summary>查看完整证据</summary><BatchSaveEvidence :candidate="candidate" /></details>
        </div>
      </article>
    </section>
  </div>
</template>
