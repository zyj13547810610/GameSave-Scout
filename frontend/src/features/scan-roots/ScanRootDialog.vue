<script setup lang="ts">
import { ref } from 'vue'
import type { GameShelfBridge, RootInput, ScanRoot } from '../../api/contracts'

const props = defineProps<{ bridge: GameShelfBridge; root?: ScanRoot }>()
const emit = defineEmits<{ saved: [root: ScanRoot]; close: [] }>()
const displayPath = ref(props.root?.displayPath ?? '')
const recursive = ref(props.root?.scanMode === 'recursive')
const maxDepth = ref(props.root?.maxDepth ?? 2)
const exclusionsText = ref(props.root?.exclusions.join('\n') ?? '')
const error = ref('')
const submitting = ref(false)

async function browse() {
  const result = await props.bridge.choose_directory()
  if (result.ok && result.data) displayPath.value = result.data
}

async function submit() {
  error.value = ''
  if (!displayPath.value.trim()) return void (error.value = '请选择游戏根目录')
  if (recursive.value && (maxDepth.value < 1 || maxDepth.value > 8)) {
    error.value = '扫描深度必须在 1 到 8 之间'
    return
  }
  const input: RootInput = {
    displayPath: displayPath.value.trim(),
    scanMode: recursive.value ? 'recursive' : 'children',
    maxDepth: recursive.value ? maxDepth.value : 1,
    exclusions: exclusionsText.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
  }
  submitting.value = true
  const result = props.root
    ? await props.bridge.update_root({
        ...input,
        rootId: props.root.id,
        enabled: props.root.enabled,
      })
    : await props.bridge.add_root(input)
  submitting.value = false
  if (!result.ok) return void (error.value = result.error.message)
  emit('saved', result.data)
}
</script>

<template>
  <section class="dialog-card" aria-labelledby="add-root-title">
    <div class="section-heading">
      <h2 id="add-root-title">{{ root ? '游戏目录设置' : '添加游戏目录' }}</h2>
      <button class="icon-button" type="button" aria-label="关闭" @click="$emit('close')">×</button>
    </div>
    <form @submit.prevent="submit">
      <label>目录路径</label>
      <div class="path-row">
        <input v-model="displayPath" data-test="display-path" :readonly="Boolean(root)" placeholder="例如 D:\\Games" />
        <button v-if="!root" type="button" @click="browse">浏览</button>
      </div>
      <label class="check-row">
        <input v-model="recursive" data-test="mode-recursive" type="checkbox" />
        扫描分组目录中的游戏
      </label>
      <label v-if="recursive">最大扫描深度</label>
      <input v-if="recursive" v-model.number="maxDepth" data-test="max-depth" type="number" min="1" max="8" />
      <label>排除规则（每行一项，可使用 glob）</label>
      <textarea v-model="exclusionsText" data-test="root-exclusions" rows="5" placeholder="tools&#10;**/cache" />
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <div class="dialog-actions">
        <button type="button" class="secondary" @click="$emit('close')">取消</button>
        <button type="submit" :disabled="submitting">{{ submitting ? '正在保存…' : root ? '保存设置' : '添加并扫描' }}</button>
      </div>
    </form>
  </section>
</template>
