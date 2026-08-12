<script setup lang="ts">
defineProps<{ query: string; status: string; engine: string; engines: string[] }>()
defineEmits<{ 'update:query': [value: string]; 'update:status': [value: string]; 'update:engine': [value: string] }>()
</script>

<template>
  <div class="library-toolbar">
    <input :value="query" type="search" placeholder="搜索游戏标题" aria-label="搜索游戏" @input="$emit('update:query', ($event.target as HTMLInputElement).value)" />
    <select :value="status" aria-label="状态筛选" @change="$emit('update:status', ($event.target as HTMLSelectElement).value)">
      <option value="all">全部状态</option><option value="installed">已安装</option><option value="missing">本体失效</option><option value="save_only">仅存档</option>
    </select>
    <select :value="engine" aria-label="引擎筛选" @change="$emit('update:engine', ($event.target as HTMLSelectElement).value)">
      <option value="all">全部引擎</option><option v-for="item in engines" :key="item" :value="item">{{ item }}</option>
    </select>
  </div>
</template>
