<script setup lang="ts">
import type { BatchSaveCandidate } from '../../api/contracts'

defineProps<{ candidate: BatchSaveCandidate }>()
</script>

<template>
  <section class="batch-save-evidence" :aria-label="`${candidate.suggestedTitle || '未知游戏'} 的证据`">
    <h3>识别证据</h3>
    <ul><li v-for="item in candidate.evidence" :key="item">{{ item }}</li></ul>
    <template v-if="candidate.representativeFiles.length">
      <h4>代表文件（{{ candidate.matchedFileCount }}）</h4>
      <ul class="batch-representative-files">
        <li v-for="file in candidate.representativeFiles" :key="`${file.name}:${file.modifiedTimeNs}`"><code>{{ file.name }}</code><small>{{ file.size }} 字节</small></li>
      </ul>
      <p v-if="candidate.representativesTruncated" class="warning-text">代表文件仅显示前 20 项。</p>
    </template>
    <template v-if="candidate.alternatives.length">
      <h4>其他可能游戏</h4>
      <ul><li v-for="item in candidate.alternatives" :key="`${item.title}:${item.reason}`"><strong>{{ item.title }}</strong><small>{{ item.reason }}</small></li></ul>
    </template>
    <dl>
      <dt>首次发现</dt><dd>{{ candidate.firstSeenAt }}</dd>
      <dt>最后发现</dt><dd>{{ candidate.lastSeenAt }}</dd>
    </dl>
  </section>
</template>
