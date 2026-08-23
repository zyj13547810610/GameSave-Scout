<script setup lang="ts">
import type { RuleDetail, RuleDraft } from '../../api/contracts'

defineProps<{
  detail: RuleDetail | null
  draft: RuleDraft | null
  loading: boolean
  error: string
}>()

defineEmits<{ back: []; edit: [] }>()
</script>

<template>
  <section class="rule-detail-pane" aria-label="规则详情">
    <div class="rule-pane-heading">
      <button class="rule-mobile-back secondary" type="button" @click="$emit('back')">返回规则列表</button>
      <h3>{{ draft ? (draft.label || '新规则') : (detail?.label ?? '规则详情') }}</h3>
    </div>
    <div data-test="rule-detail-scroll" class="rule-detail-scroll" tabindex="0">
      <p v-if="loading" class="rule-pane-message">正在读取规则详情…</p>
      <p v-else-if="error" class="inline-error" role="alert">{{ error }}</p>
      <template v-else-if="detail">
        <dl class="rule-detail-metadata">
          <dt>限定 ID</dt><dd><code>{{ detail.qualifiedId }}</code></dd>
          <dt>来源文件</dt><dd>{{ detail.sourceFile }}</dd>
          <dt>优先级</dt><dd>{{ detail.priority }}</dd>
          <dt>备注</dt><dd>{{ detail.notes ?? '无' }}</dd>
        </dl>
        <h4>YAML 预览</h4>
        <pre class="rule-yaml-preview">{{ detail.yamlPreview }}</pre>
      </template>
      <template v-else-if="draft">
        <p>规则表单将在下一实施任务接入；当前已建立安全草稿和离开确认边界。</p>
        <pre class="rule-yaml-preview">{{ JSON.stringify(draft, null, 2) }}</pre>
      </template>
      <p v-else class="rule-pane-message">从左侧选择一条规则查看详情。</p>
    </div>
    <div v-if="detail?.capabilities.edit && !draft" class="rule-detail-actions">
      <button type="button" @click="$emit('edit')">编辑规则</button>
    </div>
  </section>
</template>
