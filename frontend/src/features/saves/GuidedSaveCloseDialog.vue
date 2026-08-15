<script setup lang="ts">
import { storeToRefs } from 'pinia'
import type { GameShelfBridge } from '../../api/contracts'
import { useGuidedSaveStore } from './guidedSaveStore'

defineProps<{ bridge: GameShelfBridge }>()
const store = useGuidedSaveStore()
const { session } = storeToRefs(store)
</script>

<template>
  <div v-if="session?.closeRequested" data-test="guided-save-close-dialog" class="dialog-backdrop">
    <section class="dialog-card" role="dialog" aria-modal="true" aria-labelledby="guided-close-title">
      <h2 id="guided-close-title">仍在寻找存档</h2>
      <p>关闭 GameShelf 前，请选择如何处理当前引导式寻找会话。</p>
      <div class="dialog-actions">
        <button type="button" @click="store.resolveClose(bridge, 'return')">返回程序</button>
        <button type="button" @click="store.resolveClose(bridge, 'cancel_and_exit')">取消会话并退出</button>
        <button class="primary" type="button" @click="store.resolveClose(bridge, 'analyze_and_exit')">停止并分析后退出</button>
      </div>
    </section>
  </div>
</template>
