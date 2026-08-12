<script setup lang="ts">
import type { GameShelfBridge, ScanRoot } from '../../api/contracts'

const props = defineProps<{ bridge: GameShelfBridge; roots: ScanRoot[]; scanTasks: Record<string, string> }>()
const emit = defineEmits<{ scan: [rootId: string]; cancel: [rootId: string]; remove: [rootId: string]; remap: [rootId: string, path: string]; toggle: [root: ScanRoot, enabled: boolean] }>()

async function remap(rootId: string) {
  const result = await props.bridge.choose_directory()
  if (result.ok && result.data) emit('remap', rootId, result.data)
}
</script>

<template>
  <aside class="root-panel">
    <h2>游戏目录</h2>
    <p v-if="roots.length === 0" class="muted">尚未添加目录</p>
    <article v-for="root in roots" :key="root.id" class="root-item">
      <strong :title="root.displayPath">{{ root.displayPath }}</strong>
      <label class="check-row"><input type="checkbox" :checked="root.enabled" @change="emit('toggle', root, ($event.target as HTMLInputElement).checked)" />参与扫描</label>
      <span>{{ root.scanMode === 'children' ? '直接子目录' : `递归 ${root.maxDepth} 层` }}</span>
      <span :class="['status-text', root.lastScanStatus]">{{ root.lastScanStatus }}</span>
      <p v-if="root.lastError" class="form-error">{{ root.lastError }}</p>
      <div class="compact-actions">
        <button v-if="!scanTasks[root.id]" type="button" @click="emit('scan', root.id)">扫描</button>
        <button v-else type="button" class="danger" @click="emit('cancel', root.id)">取消</button>
        <button type="button" @click="remap(root.id)">重映射</button>
        <button type="button" class="danger" @click="emit('remove', root.id)">删除</button>
      </div>
    </article>
  </aside>
</template>
