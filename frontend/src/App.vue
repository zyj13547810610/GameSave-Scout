<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { createBridge } from './api/bridge'

const bridge = createBridge()
const state = ref<'connecting' | 'ready' | 'failed'>('connecting')
const errorMessage = ref('')

async function bootstrap() {
  state.value = 'connecting'
  const result = await bridge.bootstrap()
  if (result.ok) {
    state.value = 'ready'
    return
  }
  errorMessage.value = result.error.message
  state.value = 'failed'
}

onMounted(bootstrap)
</script>

<template>
  <main class="app-shell">
    <header><h1>GameShelf</h1></header>
    <section v-if="state === 'connecting'" class="empty-state" aria-live="polite">
      <h2>正在连接本地数据库…</h2>
    </section>
    <section v-else-if="state === 'ready'" class="empty-state" aria-labelledby="empty-title">
      <h2 id="empty-title">还没有添加游戏目录</h2>
      <p>添加一个或多个本地目录后，游戏会显示在这里。</p>
    </section>
    <section v-else class="empty-state" role="alert">
      <h2>无法连接本地数据库</h2>
      <p>{{ errorMessage }}</p>
      <button type="button" @click="bootstrap">重试</button>
    </section>
  </main>
</template>
