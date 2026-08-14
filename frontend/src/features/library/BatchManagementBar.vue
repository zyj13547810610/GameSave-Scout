<script setup lang="ts">
defineProps<{
  selectedCount: number
  installedCount: number
  missingCount: number
  busy: boolean
  canSelectVisible: boolean
}>()

defineEmits<{
  selectVisible: []
  clear: []
  exit: []
  remove: []
}>()
</script>

<template>
  <section data-test="batch-management-bar" class="batch-management-bar" aria-label="批量管理">
    <p data-test="batch-counts">
      已选择 {{ selectedCount }} 个
      <span>已安装 {{ installedCount }}</span>
      <span>失效 {{ missingCount }}</span>
    </p>
    <div class="batch-actions">
      <button data-test="select-visible-games" type="button" :disabled="busy || !canSelectVisible" @click="$emit('selectVisible')">全选当前结果</button>
      <button type="button" :disabled="busy || selectedCount === 0" @click="$emit('clear')">清空选择</button>
      <button type="button" :disabled="busy" @click="$emit('exit')">退出批量管理</button>
      <button data-test="batch-delete" class="danger" type="button" :disabled="busy || selectedCount === 0" @click="$emit('remove')">{{ busy ? '处理中…' : '删除所选' }}</button>
    </div>
  </section>
</template>
