<script setup lang="ts">
import type { CoverWizardSettings, Game, TaskSnapshot } from '../../api/contracts'

defineProps<{
  game: Game | null
  settings: CoverWizardSettings
  sourceActive: boolean
  task: TaskSnapshot | null
}>()
defineEmits<{
  vndbCurrent: []
  vndbAll: []
  shallow: []
  directory: []
  paste: []
  files: [files: FileList]
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
    <p v-if="!settings.coverOnlineEnabled" class="cover-privacy-note">VNDB 默认关闭；开启后只发送游戏标题，不发送安装路径或本地文件。</p>
    <p v-if="task" class="cover-task-progress" role="status">
      {{ task.message || '正在收集候选' }}
      <span v-if="task.progress.total !== null">{{ task.progress.completed }}/{{ task.progress.total }}</span>
    </p>
  </section>
</template>
