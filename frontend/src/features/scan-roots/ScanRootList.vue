<script setup lang="ts">
import type { GameShelfBridge, ScanResult, ScanRoot, TaskSnapshot } from '../../api/contracts'

const props = defineProps<{
  bridge: GameShelfBridge
  roots: ScanRoot[]
  scanTasks: Record<string, string>
  taskSnapshots: Record<string, TaskSnapshot>
}>()
const emit = defineEmits<{ scan: [rootId: string]; cancel: [rootId: string]; edit: [root: ScanRoot]; remove: [rootId: string]; remap: [rootId: string, path: string]; toggle: [root: ScanRoot, enabled: boolean] }>()

async function remap(rootId: string) {
  const result = await props.bridge.choose_directory()
  if (result.ok && result.data) emit('remap', rootId, result.data)
}

const stageLabels: Record<string, string> = {
  preparing: '正在准备',
  discovering: '正在查找游戏',
  reconciling: '正在更新游戏库',
  completed: '扫描完成',
  cancelled: '扫描已取消',
  failed: '扫描失败',
  unavailable: '根目录不可访问',
}

function numberDetail(snapshot: TaskSnapshot, key: string): number {
  const value = snapshot.details?.[key]
  return typeof value === 'number' ? value : 0
}

function textDetail(snapshot: TaskSnapshot, key: string): string {
  const value = snapshot.details?.[key]
  return typeof value === 'string' ? value : ''
}

function scanResult(snapshot: TaskSnapshot): ScanResult | null {
  if (snapshot.status !== 'completed' || !snapshot.result) return null
  return snapshot.result as ScanResult
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
      <section v-if="taskSnapshots[root.id] && scanTasks[root.id]" data-test="scan-progress" class="scan-progress" aria-live="polite">
        <div data-test="indeterminate-progress" class="indeterminate-progress"><span /></div>
        <strong>{{ stageLabels[textDetail(taskSnapshots[root.id], 'stage')] ?? taskSnapshots[root.id].message }}</strong>
        <span v-if="textDetail(taskSnapshots[root.id], 'currentPath')" class="scan-current" :title="textDetail(taskSnapshots[root.id], 'currentPath')">{{ textDetail(taskSnapshots[root.id], 'currentPath') }}</span>
        <small>
          已检查 {{ numberDetail(taskSnapshots[root.id], 'directoriesScanned') }} 个目录 ·
          发现 {{ numberDetail(taskSnapshots[root.id], 'discovered') }} 个游戏 ·
          不可访问 {{ numberDetail(taskSnapshots[root.id], 'inaccessibleDirectories') }} 个 ·
          警告 {{ numberDetail(taskSnapshots[root.id], 'warnings') }} 项 ·
          {{ numberDetail(taskSnapshots[root.id], 'elapsedSeconds') }} 秒
        </small>
      </section>
      <section v-else-if="taskSnapshots[root.id]" data-test="scan-summary" :class="['scan-summary', taskSnapshots[root.id].status]" aria-live="polite">
        <template v-if="scanResult(taskSnapshots[root.id])">
          <strong>扫描完成</strong>
          <span>
            发现 {{ scanResult(taskSnapshots[root.id])?.discovered }} ·
            新增 {{ scanResult(taskSnapshots[root.id])?.added }} ·
            更新 {{ scanResult(taskSnapshots[root.id])?.updated }} ·
            失效 {{ scanResult(taskSnapshots[root.id])?.missing }}
          </span>
        </template>
        <template v-else>
          <strong>{{ stageLabels[textDetail(taskSnapshots[root.id], 'stage')] ?? taskSnapshots[root.id].message }}</strong>
          <span>{{ taskSnapshots[root.id].message }}</span>
        </template>
        <small>用时 {{ numberDetail(taskSnapshots[root.id], 'elapsedSeconds') }} 秒</small>
      </section>
      <p v-if="root.lastError" class="form-error">{{ root.lastError }}</p>
      <div class="compact-actions">
        <button v-if="!scanTasks[root.id]" type="button" @click="emit('scan', root.id)">扫描</button>
        <button v-else type="button" class="danger" @click="emit('cancel', root.id)">取消</button>
        <button data-test="edit-root" type="button" @click="emit('edit', root)">设置</button>
        <button type="button" @click="remap(root.id)">重映射</button>
        <button type="button" class="danger" @click="emit('remove', root.id)">删除</button>
      </div>
    </article>
  </aside>
</template>
