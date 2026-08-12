<script setup lang="ts">
import type { EngineDetection, EngineSelection } from '../../api/contracts'

defineProps<{ adopted: EngineSelection; detected: EngineDetection | null }>()
</script>

<template>
  <section class="engine-details" aria-labelledby="engine-details-title">
    <h3 id="engine-details-title">游戏引擎</h3>
    <p><strong>当前：{{ adopted.label }}</strong><span v-if="adopted.manual" class="engine-flag">手动设置</span></p>
    <template v-if="detected">
      <p class="engine-suggestion">
        {{ detected.ambiguous ? '疑似' : '自动建议' }}：{{ detected.label }}
        <span v-if="detected.confidence"> · 置信度：{{ detected.confidence }}</span>
      </p>
      <p v-if="detected.alternatives.length" class="engine-alternatives">
        候选：{{ detected.alternatives.map((item) => item.label).join('、') }}
      </p>
      <span v-if="detected.experimental" class="engine-flag warning">实验性识别</span>
      <details v-if="detected.evidence.length" class="engine-evidence">
        <summary>识别依据（{{ detected.evidence.length }}）</summary>
        <ul>
          <li v-for="item in detected.evidence" :key="`${item.code}:${item.path ?? ''}`">
            {{ item.detail }}<small v-if="item.path">{{ item.path }}</small>
          </li>
        </ul>
      </details>
    </template>
    <p v-else class="engine-suggestion">暂未找到可靠的自动识别结果。</p>
  </section>
</template>
