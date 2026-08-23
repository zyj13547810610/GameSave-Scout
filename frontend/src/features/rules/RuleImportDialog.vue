<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive } from 'vue'
import type { RuleImportDecision, RuleImportPreview } from '../../api/contracts'

const props = defineProps<{ preview: RuleImportPreview; busy: boolean; error: string }>()
const emit = defineEmits<{ confirm: [decisions: RuleImportDecision[]]; close: [] }>()
type DecisionState = { action: RuleImportDecision['action'] | ''; newRuleId: string }
const decisions = reactive<Record<string, DecisionState>>({})

for (const item of props.preview.items) {
  decisions[item.itemId] = {
    action: item.valid && item.conflict === 'none' && item.allowedDecisions.includes('import')
      ? 'import'
      : !item.valid ? 'skip' : '',
    newRuleId: '',
  }
}

const canConfirm = computed(() => props.preview.items.every((item) => {
  const decision = decisions[item.itemId]
  if (!decision || !decision.action || !item.allowedDecisions.includes(decision.action)) return false
  return decision.action !== 'new_id' || /^[a-z0-9_]{1,80}$/.test(decision.newRuleId)
}))

function label(action: RuleImportDecision['action']) {
  return { import: '导入', replace: '替换用户规则', new_id: '使用新 ID', skip: '跳过' }[action]
}

function submit() {
  if (!canConfirm.value || props.busy) return
  emit('confirm', props.preview.items.map((item) => {
    const decision = decisions[item.itemId]!
    return {
      itemId: item.itemId,
      action: decision.action as RuleImportDecision['action'],
      newRuleId: decision.action === 'new_id' ? decision.newRuleId : null,
    }
  }))
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && !props.busy) emit('close')
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="dialog-backdrop rule-dialog-backdrop" @click.self="!busy && $emit('close')">
    <section data-test="rule-import-dialog" class="dialog-card rule-import-dialog" role="dialog" aria-modal="true" aria-labelledby="rule-import-title">
      <h3 id="rule-import-title">导入规则预览</h3>
      <p>每个文件都必须选择一个处理方式；整批确认后才会写入。</p>
      <div class="rule-import-items">
        <article v-for="item in preview.items" :key="item.itemId" class="rule-import-item">
          <strong>{{ item.fileName }}</strong>
          <span>{{ item.valid ? (item.qualifiedId ?? '有效规则') : '无效文件' }}</span>
          <ul v-if="item.errors.length"><li v-for="errorItem in item.errors" :key="errorItem">{{ errorItem }}</li></ul>
          <label>处理方式
            <select :data-test="`import-decision-${item.itemId}`" v-model="decisions[item.itemId]!.action" :disabled="busy">
              <option v-if="item.valid && item.conflict !== 'none'" value="">请选择</option>
              <option v-for="action in item.allowedDecisions" :key="action" :value="action">{{ label(action) }}</option>
            </select>
          </label>
          <label v-if="decisions[item.itemId]?.action === 'new_id'">新规则 ID
            <input :data-test="`import-new-id-${item.itemId}`" v-model="decisions[item.itemId]!.newRuleId" :disabled="busy" pattern="[a-z0-9_]+">
          </label>
        </article>
      </div>
      <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
      <div class="dialog-actions">
        <button class="secondary" type="button" :disabled="busy" @click="$emit('close')">取消</button>
        <button data-test="confirm-rule-import" type="button" :disabled="busy || !canConfirm" @click="submit">{{ busy ? '正在导入…' : '确认导入' }}</button>
      </div>
    </section>
  </div>
</template>
