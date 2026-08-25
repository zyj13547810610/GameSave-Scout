<script setup lang="ts">
import { ref } from 'vue'
import type { GameSaveScoutBridge, SaveLocationKind } from '../../api/contracts'

const props = defineProps<{ gameId: string; bridge: GameSaveScoutBridge }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const kind = ref<SaveLocationKind>('directory')
const selectedPath = ref('')
const globPattern = ref('*.sav')
const registryPath = ref('')
const busy = ref(false)
const message = ref('')

async function choosePath() {
  message.value = ''
  const result = await props.bridge.choose_save_path({ gameId: props.gameId, kind: kind.value })
  if (!result.ok) return void (message.value = result.error.message)
  if (result.data) selectedPath.value = result.data
}

async function submit() {
  if (busy.value) return
  message.value = ''
  const path = pathForSubmission()
  if (!path) return
  busy.value = true
  const result = await props.bridge.add_manual_save_location({
    gameId: props.gameId,
    kind: kind.value,
    selectedPath: path,
  })
  busy.value = false
  if (!result.ok) return void (message.value = result.error.message)
  emit('saved')
}

function pathForSubmission(): string | null {
  if (kind.value === 'registry') {
    const clean = registryPath.value.trim()
    if (!/^HKEY_(CURRENT_USER|LOCAL_MACHINE)\\[^\\].+/i.test(clean)) {
      message.value = '请输入以 HKEY_CURRENT_USER 或 HKEY_LOCAL_MACHINE 开头的完整注册表路径。'
      return null
    }
    return clean
  }
  if (!selectedPath.value) {
    message.value = kind.value === 'file' ? '请先选择一个存档文件。' : '请先选择一个存档目录。'
    return null
  }
  if (kind.value !== 'glob') return selectedPath.value
  const pattern = globPattern.value.trim()
  if (!pattern || !/[*?[]/.test(pattern) || /[\\/]/.test(pattern) || pattern.includes('..')) {
    message.value = '文件模式需包含 *、? 或 [，且不能包含目录分隔符或 ..。'
    return null
  }
  return `${selectedPath.value.replace(/[\\/]+$/, '')}\\${pattern}`
}
</script>

<template>
  <div class="save-add-dialog" data-test="add-save-dialog">
    <form @submit.prevent="submit">
      <div class="save-dialog-heading">
        <h4>手动添加存档位置</h4>
        <button type="button" class="icon-button" aria-label="关闭添加存档位置" @click="emit('close')">×</button>
      </div>
      <label>
        位置类型
        <select data-test="save-kind" v-model="kind" @change="selectedPath = ''; message = ''">
          <option value="directory">目录</option>
          <option value="file">单个文件</option>
          <option value="glob">文件模式</option>
          <option value="registry">注册表偏好数据</option>
        </select>
      </label>

      <template v-if="kind === 'registry'">
        <label>
          注册表路径
          <input data-test="registry-path" v-model="registryPath" placeholder="HKEY_CURRENT_USER\Software\厂商\游戏" />
        </label>
      </template>
      <template v-else>
        <div class="path-picker-row">
          <button data-test="choose-save-path" type="button" @click="choosePath">
            {{ kind === 'file' ? '选择文件' : '选择目录' }}
          </button>
          <span>{{ selectedPath || '尚未选择' }}</span>
        </div>
        <label v-if="kind === 'glob'">
          文件模式
          <input data-test="glob-pattern" v-model="globPattern" placeholder="*.sav" />
        </label>
      </template>

      <p v-if="message" class="inline-error" role="alert">{{ message }}</p>
      <div class="compact-actions">
        <button type="submit" :disabled="busy">{{ busy ? '正在添加…' : '添加' }}</button>
        <button type="button" class="secondary" @click="emit('close')">取消</button>
      </div>
    </form>
  </div>
</template>
