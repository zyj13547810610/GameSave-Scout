<script setup lang="ts">
defineProps<{
  selectedCount: number
  installedCount: number
  missingCount: number
  saveOnlyCount: number
  busy: boolean
  canSelectVisible: boolean
  canRemove: boolean
}>()

defineEmits<{
  selectVisible: []
  clear: []
  exit: []
  remove: []
  group: [event: MouseEvent]
}>()
</script>

<template>
  <section data-test="batch-management-bar" class="batch-management-bar" aria-label="批量管理">
    <p data-test="batch-counts">
      已选择 {{ selectedCount }} 个
      <span>已安装 {{ installedCount }}</span>
      <span>失效 {{ missingCount }}</span>
      <span>仅存档 {{ saveOnlyCount }}</span>
    </p>
    <p v-if="saveOnlyCount" class="batch-delete-hint">仅存档记录不能通过批量移除删除</p>
    <div class="batch-actions">
      <button data-test="select-visible-games" type="button" :disabled="busy || !canSelectVisible" @click="$emit('selectVisible')">全选当前结果</button>
      <button type="button" :disabled="busy || selectedCount === 0" @click="$emit('clear')">清空选择</button>
      <button type="button" :disabled="busy" @click="$emit('exit')">退出批量管理</button>
      <button data-test="batch-group" type="button" :disabled="busy || selectedCount === 0" @click="$emit('group', $event)">调整分组</button>
      <button
        data-test="batch-delete"
        class="danger"
        type="button"
        :disabled="busy || !canRemove"
        :title="saveOnlyCount ? '仅存档记录不能通过批量移除删除' : undefined"
        @click="$emit('remove')"
      >{{ busy ? '处理中…' : '删除所选' }}</button>
    </div>
  </section>
</template>
