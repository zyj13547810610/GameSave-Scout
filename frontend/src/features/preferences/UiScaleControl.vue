<script setup lang="ts">
import { isUiScale, UI_SCALE_OPTIONS, type UiScale } from './uiScale'

defineProps<{ modelValue: UiScale }>()
const emit = defineEmits<{ 'update:modelValue': [value: UiScale] }>()

function update(event: Event) {
  const value = Number((event.target as HTMLSelectElement).value)
  if (isUiScale(value)) emit('update:modelValue', value)
}
</script>

<template>
  <label class="ui-scale-control">
    <span class="ui-scale-label">界面缩放</span>
    <select data-test="ui-scale" :value="modelValue" @change="update">
      <option v-for="scale in UI_SCALE_OPTIONS" :key="scale" :value="scale">
        {{ Math.round(scale * 100) }}%
      </option>
    </select>
  </label>
</template>
