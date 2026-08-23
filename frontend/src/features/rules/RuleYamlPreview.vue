<script setup lang="ts">
defineProps<{ yaml: string | null }>()
</script>

<template>
  <section class="rule-yaml-section">
    <h4>规范化 YAML 预览</h4>
    <pre data-test="rule-yaml-preview" class="rule-yaml-preview"><code>{{ yaml ?? '草稿通过验证后显示规范化 YAML。' }}</code></pre>
  </section>
</template>
