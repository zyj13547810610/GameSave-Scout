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
  remove: []
  group: [event: MouseEvent]
}>()

const saveOnlyDeleteHint = '仅存档卡片不能批量删除；请打开详情删除，或前往批量存档撤销创建'
</script>

<template>
  <section data-test="batch-management-bar" class="batch-management-bar" aria-label="批量管理">
    <p data-test="batch-counts">
      已选择 {{ selectedCount }} 个
      <span>已安装 {{ installedCount }}</span>
      <span>失效 {{ missingCount }}</span>
      <span>仅存档 {{ saveOnlyCount }}</span>
    </p>
    <p v-if="saveOnlyCount" class="batch-delete-hint">{{ saveOnlyDeleteHint }}</p>
    <div class="batch-actions">
      <button data-test="select-visible-games" type="button" :disabled="busy || !canSelectVisible" @click="$emit('selectVisible')">全选当前结果</button>
      <button type="button" :disabled="busy || selectedCount === 0" @click="$emit('clear')">清空选择</button>
      <button data-test="batch-group" type="button" :disabled="busy || selectedCount === 0" @click="$emit('group', $event)">调整分组</button>
      <button
        data-test="batch-delete"
        class="danger"
        type="button"
        :disabled="busy || !canRemove"
        :title="saveOnlyCount ? saveOnlyDeleteHint : undefined"
        @click="$emit('remove')"
      >{{ busy ? '处理中…' : '删除所选' }}</button>
    </div>
  </section>
</template>
