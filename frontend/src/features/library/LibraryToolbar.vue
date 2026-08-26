<script setup lang="ts">
import type { GameGroup } from '../../api/contracts'

defineProps<{
  query: string
  status: string
  engine: string
  group: string
  engines: string[]
  groups: GameGroup[]
}>()
defineEmits<{
  'update:query': [value: string]
  'update:status': [value: string]
  'update:engine': [value: string]
  'update:group': [value: string]
}>()
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
    <select :value="group" aria-label="分组筛选" @change="$emit('update:group', ($event.target as HTMLSelectElement).value)">
      <option value="all">全部分组</option>
      <option value="ungrouped">未分组</option>
      <option v-for="item in groups" :key="item.id" :value="item.id">{{ item.name }}</option>
    </select>
  </div>
</template>
