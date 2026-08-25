<script setup lang="ts">
import type { GameSaveScoutBridge, RuleDiagnostic } from '../../api/contracts'

const props = defineProps<{
  bridge: GameSaveScoutBridge
  diagnostics: RuleDiagnostic[]
}>()

function safeName(sourceName: string) {
  return sourceName.split(/[\\/]/).at(-1) || '未知文件'
}

async function openDirectory(target: 'user' | 'legacy') {
  await props.bridge.open_rule_directory({ target })
}
</script>

<template>
  <details v-if="diagnostics.length" class="rule-diagnostics">
    <summary>规则诊断（{{ diagnostics.length }}）</summary>
    <ul>
      <li v-for="(item, index) in diagnostics" :key="`${item.code}-${index}`" :class="item.severity">
        <strong>{{ safeName(item.sourceName) }}</strong>
        <code>{{ item.code }}</code>
        <span>{{ item.message }}</span>
      </li>
    </ul>
    <div class="compact-actions">
      <button class="secondary" type="button" @click="openDirectory('user')">打开用户规则目录</button>
      <button class="secondary" type="button" @click="openDirectory('legacy')">打开旧规则目录</button>
    </div>
  </details>
</template>
