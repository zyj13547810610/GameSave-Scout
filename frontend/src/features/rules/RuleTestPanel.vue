<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Game, RuleTestResult } from '../../api/contracts'

const props = defineProps<{
  games: Pick<Game, 'id' | 'title' | 'status'>[]
  result: RuleTestResult | null
  busy: boolean
  canMarkVerified: boolean
}>()
const emit = defineEmits<{ test: [gameId: string]; markVerified: [] }>()
const selectedGameId = ref('')
const installedGames = computed(() => props.games.filter((game) => game.status === 'installed'))
</script>

<template>
  <section class="rule-test-panel">
    <h4>在本地游戏上测试</h4>
    <p>测试只读取所选游戏的受限目录和规则声明，不会启动游戏。</p>
    <div class="rule-test-controls">
      <select v-model="selectedGameId" data-test="rule-test-game" aria-label="选择测试游戏">
        <option value="">请选择已安装游戏</option>
        <option v-for="game in installedGames" :key="game.id" :value="game.id">{{ game.title }}</option>
      </select>
      <button data-test="test-rule" type="button" :disabled="busy || !selectedGameId" @click="emit('test', selectedGameId)">{{ busy ? '正在测试…' : '执行测试' }}</button>
    </div>
    <section v-if="result" class="rule-test-result" aria-live="polite">
      <h5>{{ result.matched ? '规则命中' : '规则未命中' }}</h5>
      <p>{{ result.summary }}</p>
      <ul v-if="result.evidence.length"><li v-for="item in result.evidence" :key="item">{{ item }}</li></ul>
      <ul v-if="result.expandedLocations.length" class="rule-test-locations">
        <li v-for="location in result.expandedLocations" :key="`${location.kind}:${location.pathTemplate}`">
          <strong>{{ location.exists ? '已找到' : '未找到' }}</strong>
          <code>{{ location.pathTemplate }}</code>
          <span>{{ location.displayPath }}</span>
        </li>
      </ul>
      <button
        v-if="result.verificationToken"
        data-test="mark-rule-verified"
        type="button"
        :disabled="!canMarkVerified"
        @click="$emit('markVerified')"
      >标记为用户已验证</button>
    </section>
  </section>
</template>
