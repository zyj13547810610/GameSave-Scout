<script setup lang="ts">
import { computed } from 'vue'
import type { CoverWizardSettings, Game, TaskSnapshot } from '../../api/contracts'

const props = defineProps<{
  game: Game | null
  settings: CoverWizardSettings
  sourceActive: boolean
  task: TaskSnapshot | null
  includeUsed: boolean
}>()

const displayedCompleted = computed(() => {
  const task = props.task
  const total = task?.progress.total
  if (!task || total === null || total === undefined) return 0
  if (task.status === 'completed') return total
  return Math.min(Math.max(task.progress.completed, 0), total)
})

const progressMax = computed(() => Math.max(props.task?.progress.total ?? 1, 1))

const taskMessage = computed(() => {
  const task = props.task
  if (!task) return ''
  if (task.message) return task.message
  if (task.status === 'queued' || task.status === 'running') return '正在收集候选…'
  if (task.status === 'completed') return '候选收集完成'
  if (task.status === 'cancelled') return '任务已取消'
  return task.error?.message ?? '候选收集失败'
})

defineEmits<{
  vndbCurrent: []
  vndbAll: []
  shallow: []
  directory: []
  paste: []
  files: [files: FileList]
  'update:includeUsed': [value: boolean]
}>()
</script>

<template>
  <section class="cover-source-toolbar" aria-label="候选来源">
    <div class="cover-source-actions">
      <button type="button" :disabled="!game || !settings.coverOnlineEnabled || sourceActive" @click="$emit('vndbCurrent')">VNDB 搜索当前</button>
      <button type="button" :disabled="!settings.coverOnlineEnabled || sourceActive" @click="$emit('vndbAll')">VNDB 搜索全部</button>
      <button type="button" :disabled="!game || !game.installPath || sourceActive" @click="$emit('shallow')">浅层扫描</button>
      <button type="button" :disabled="sourceActive" @click="$emit('directory')">导入封面目录</button>
      <button type="button" class="secondary" :disabled="!game || sourceActive" @click="$emit('paste')">粘贴图片</button>
      <label class="cover-file-button" :class="{ disabled: !game || sourceActive }">
        拖入或选择图片
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp,image/bmp"
          multiple
          :disabled="!game || sourceActive"
          @change="($event.target as HTMLInputElement).files && $emit('files', ($event.target as HTMLInputElement).files!)"
        >
      </label>
    </div>
    <label class="cover-include-used">
      <input
        data-test="cover-include-used"
        type="checkbox"
        :checked="includeUsed"
        @change="$emit('update:includeUsed', ($event.target as HTMLInputElement).checked)"
      >
      显示已使用图片
    </label>
    <p v-if="!settings.coverOnlineEnabled" class="cover-privacy-note">VNDB 默认关闭；开启后只发送游戏标题，不发送版本号、安装路径或本地文件。</p>
    <div
      v-if="task"
      data-test="cover-task-progress"
      class="cover-task-panel"
      :class="`status-${task.status}`"
    >
      <p class="cover-task-progress" role="status" aria-live="polite">
        <span>{{ taskMessage }}</span>
        <strong v-if="task.progress.total !== null">
          {{ displayedCompleted }}/{{ task.progress.total }}
        </strong>
      </p>
      <progress
        aria-label="候选收集进度"
        :max="progressMax"
        :value="task.progress.total === null ? undefined : displayedCompleted"
      />
    </div>
  </section>
</template>
