<script setup lang="ts">
defineProps<{ label: string; experimental?: boolean }>()
</script>

<template>
  <span class="engine-badge">{{ label }}<small v-if="experimental">实验性</small></span>
</template>
