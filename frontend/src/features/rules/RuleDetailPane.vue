<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { Game, RuleDetail, RuleDraft, RuleDraftValidation, RuleTestResult } from '../../api/contracts'
import RuleEditorForm from './RuleEditorForm.vue'
import RuleTestPanel from './RuleTestPanel.vue'

const props = defineProps<{
  detail: RuleDetail | null
  draft: RuleDraft | null
  validation: RuleDraftValidation | null
  testResult: RuleTestResult | null
  games: Pick<Game, 'id' | 'title' | 'status'>[]
  loading: boolean
  busy: boolean
  testing: boolean
  dirty: boolean
  canMarkVerified: boolean
  error: string
  mutationError: string
  notice: string
}>()

const emit = defineEmits<{
  back: []
  edit: []
  updateDraft: [draft: RuleDraft]
  validate: [draft: RuleDraft]
  test: [gameId: string]
  markVerified: []
  save: []
  copy: [qualifiedId: string]
  toggle: [detail: RuleDetail]
  delete: [qualifiedId: string]
  export: [qualifiedId: string]
}>()

const pendingAction = ref<'toggle' | 'delete' | null>(null)
const actionTrigger = ref<HTMLElement | null>(null)
const testPanelAnchor = ref<HTMLElement | null>(null)

function requestDanger(action: 'toggle' | 'delete', event: MouseEvent) {
  if (!props.detail || props.busy) return
  actionTrigger.value = event.currentTarget as HTMLElement
  pendingAction.value = action
}

async function closeDanger() {
  pendingAction.value = null
  await nextTick()
  actionTrigger.value?.focus()
}

function confirmDanger() {
  if (!props.detail || !pendingAction.value) return
  if (pendingAction.value === 'toggle') emit('toggle', props.detail)
  else emit('delete', props.detail.qualifiedId)
  void closeDanger()
}

async function focusTestPanel() {
  await nextTick()
  const anchor = testPanelAnchor.value
  if (!anchor) return
  anchor.scrollIntoView({ behavior: 'smooth', block: 'start' })
  anchor.focus({ preventScroll: true })
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && pendingAction.value) void closeDanger()
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
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
      <template v-else-if="draft">
        <RuleEditorForm
          :draft="draft"
          :mode="detail ? 'edit' : 'create'"
          :validation="validation"
          :busy="busy"
          :dirty="dirty"
          @update:draft="$emit('updateDraft', $event)"
          @validate="$emit('validate', $event)"
          @test="focusTestPanel"
          @save="$emit('save')"
        />
        <div ref="testPanelAnchor" class="rule-test-anchor" data-test="rule-test-anchor" tabindex="-1">
          <RuleTestPanel
            :games="games"
            :result="testResult"
            :busy="testing"
            :can-mark-verified="canMarkVerified"
            @test="$emit('test', $event)"
            @mark-verified="$emit('markVerified')"
          />
        </div>
      </template>
      <template v-else-if="detail">
        <RuleEditorForm
          :draft="detail.draft"
          mode="readonly"
          :validation="{
            valid: true, normalizedDraft: detail.draft, yamlPreview: detail.yamlPreview,
            errorCode: null, message: '当前有效规则。',
          }"
          :busy="busy"
          :dirty="false"
        />
        <RuleTestPanel
          :games="games"
          :result="testResult"
          :busy="testing"
          :can-mark-verified="false"
          @test="$emit('test', $event)"
        />
      </template>
      <p v-else class="rule-pane-message">从左侧选择一条规则查看详情。</p>
      <p v-if="mutationError" class="inline-error" role="alert">{{ mutationError }}</p>
      <p v-if="notice" class="rule-operation-notice" role="status">{{ notice }}</p>
    </div>
    <div v-if="detail && !draft" class="rule-detail-actions compact-actions">
      <button v-if="detail.capabilities.edit" type="button" :disabled="busy" @click="$emit('edit')">编辑</button>
      <button v-if="detail.capabilities.copy" class="secondary" type="button" :disabled="busy" @click="$emit('copy', detail.qualifiedId)">复制为用户规则</button>
      <button v-if="detail.capabilities.toggle" class="secondary" type="button" :disabled="busy" @click="requestDanger('toggle', $event)">{{ detail.enabled ? '停用' : '启用' }}</button>
      <button v-if="detail.capabilities.export" class="secondary" type="button" :disabled="busy" @click="$emit('export', detail.qualifiedId)">导出</button>
      <button v-if="detail.capabilities.delete" class="danger" type="button" :disabled="busy" @click="requestDanger('delete', $event)">删除</button>
    </div>

    <div v-if="pendingAction" class="dialog-backdrop rule-dialog-backdrop" @click.self="closeDanger">
      <section data-test="rule-action-dialog" class="dialog-card rule-action-dialog" role="alertdialog" aria-modal="true">
        <h3>{{ pendingAction === 'delete' ? '删除用户规则' : `${detail?.enabled ? '停用' : '启用'}规则` }}</h3>
        <p v-if="pendingAction === 'delete'">删除后无法从应用内撤销，确认删除 {{ detail?.label }}？</p>
        <p v-else>确认{{ detail?.enabled ? '停用' : '启用' }} {{ detail?.label }}？变更只影响下一次任务。</p>
        <div class="dialog-actions">
          <button class="secondary" type="button" @click="closeDanger">取消</button>
          <button :class="{ danger: pendingAction === 'delete' }" type="button" @click="confirmDanger">确认</button>
        </div>
      </section>
    </div>
  </section>
</template>
