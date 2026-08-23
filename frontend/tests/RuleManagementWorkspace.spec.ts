import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'
import type { RuleDetail } from '../src/api/contracts'
import { createMockBridge, ok } from '../src/api/mockBridge'
import RuleManagementWorkspace from '../src/features/rules/RuleManagementWorkspace.vue'
import '../src/styles/base.css'

function ruleDetail(overrides: Partial<RuleDetail> = {}): RuleDetail {
  return {
    qualifiedId: 'builtin:kiri', ruleId: 'kiri', label: 'KiriKiri', ruleType: 'engine',
    source: 'builtin', status: 'formal', enabled: true, priority: 100,
    notes: null, references: [], sourceFile: 'engines.yaml', yamlPreview: 'id: kiri',
    draft: {
      version: '1', id: 'kiri', label: 'KiriKiri', type: 'engine', status: 'formal',
      priority: 100, enabled: true, notes: null, references: [], threshold: .7,
      all: [{ op: 'path_exists', path: 'data.xp3', weight: 1 }], any: [], negative: [],
    },
    capabilities: { edit: false, copy: true, test: true, toggle: true, delete: false, export: true },
    ...overrides,
  }
}

describe('RuleManagementWorkspace', () => {
  it('keeps controls outside two independently scrollable panes', async () => {
    const bridge = createMockBridge({
      list_rules: async () => ok({ items: [], total: 0 }),
    })
    const wrapper = mount(RuleManagementWorkspace, {
      attachTo: document.body,
      props: { bridge },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()

    expect(wrapper.get('[data-test="rule-workspace-controls"]')).toBeTruthy()
    expect(getComputedStyle(wrapper.get('[data-test="rule-list-scroll"]').element).overflowY).toBe('auto')
    expect(getComputedStyle(wrapper.get('[data-test="rule-detail-scroll"]').element).overflowY).toBe('auto')
    expect(getComputedStyle(wrapper.get('[data-test="rule-management-workspace"]').element).overflow).toBe('hidden')
    wrapper.unmount()
  })

  it('uses three tabs and hides the rule list for Ludusavi', async () => {
    const wrapper = mount(RuleManagementWorkspace, {
      props: { bridge: createMockBridge() },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()

    expect(wrapper.findAll('[role="tab"]')).toHaveLength(3)
    await wrapper.get('[data-test="rules-tab-ludusavi"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="rule-list-scroll"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="ludusavi-settings"]').exists()).toBe(true)
  })

  it('confirms before emitting leave when the draft is dirty', async () => {
    const pinia = createPinia()
    const wrapper = mount(RuleManagementWorkspace, {
      props: { bridge: createMockBridge() },
      global: { plugins: [pinia] },
    })
    await flushPromises()
    const store = (await import('../src/features/rules/ruleManagementStore')).useRuleManagementStore(pinia)
    store.dirty = true
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)

    await wrapper.get('[data-test="leave-rule-management"]').trigger('click')
    expect(wrapper.emitted('leave')).toBeUndefined()
    await wrapper.get('[data-test="leave-rule-management"]').trigger('click')
    expect(wrapper.emitted('leave')).toHaveLength(1)
    expect(store.dirty).toBe(false)
    confirm.mockRestore()
  })

  it('declares a 60rem narrow layout with list/detail step navigation', () => {
    const responsiveRule = Array.from(document.styleSheets)
      .flatMap((sheet) => Array.from(sheet.cssRules))
      .find((rule) => rule.cssText.startsWith('@container (max-width: 60rem)'))

    expect(responsiveRule).toBeDefined()
    expect(responsiveRule?.cssText).toContain('.rule-workspace-body')
    expect(responsiveRule?.cssText).toContain('.rule-mobile-back')
  })

  it('keeps builtin rules read-only and confirms dangerous toggles with focus restoration', async () => {
    const initial = ruleDetail()
    const toggled = ruleDetail({ enabled: false, draft: { ...initial.draft, enabled: false } })
    const setEnabled = vi.fn(async () => ok({ detail: toggled, generation: 4 }))
    const testRule = vi.fn(async () => ok({
      matched: true, summary: '命中 KiriKiri', evidence: ['data.xp3'],
      expandedLocations: [], verificationToken: 'token-1',
    }))
    const bridge = createMockBridge({
      async list_rules() { return ok({ items: [initial], total: 1 }) },
      async get_rule() { return ok(initial) },
      set_rule_enabled: setEnabled,
      test_rule_draft: testRule,
    })
    const wrapper = mount(RuleManagementWorkspace, {
      attachTo: document.body,
      props: { bridge, games: [{ id: 'game-1', title: 'Alice', status: 'installed' }] },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()
    await wrapper.get('.rule-list-item').trigger('click')
    await flushPromises()
    expect(wrapper.get('input[name="label"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('复制为用户规则')
    expect(wrapper.text()).toContain('导出')
    await wrapper.get('[data-test="rule-test-game"]').setValue('game-1')
    await wrapper.get('[data-test="test-rule"]').trigger('click')
    await flushPromises()
    expect(testRule).toHaveBeenCalledWith({ draft: initial.draft, gameId: 'game-1' })
    expect(wrapper.text()).toContain('命中 KiriKiri')

    const toggle = wrapper.findAll('button').find((button) => button.text() === '停用')!
    await toggle.trigger('click')
    expect(wrapper.find('[data-test="rule-action-dialog"]').exists()).toBe(true)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(wrapper.find('[data-test="rule-action-dialog"]').exists()).toBe(false)
    expect(document.activeElement).toBe(toggle.element)

    await toggle.trigger('click')
    await wrapper.get('[data-test="rule-action-dialog"] .dialog-actions button:last-child').trigger('click')
    await flushPromises()
    expect(setEnabled).toHaveBeenCalledWith({ qualifiedId: 'builtin:kiri', enabled: false })
    expect(wrapper.text()).toContain('只影响下一次任务')
    wrapper.unmount()
  })

  it('imports a preview as one batch and selects the first imported rule', async () => {
    const imported = ruleDetail({
      qualifiedId: 'user:fresh', ruleId: 'fresh', label: 'Fresh', source: 'user', status: 'experimental',
      draft: { ...ruleDetail().draft, id: 'fresh', label: 'Fresh', status: 'experimental' },
      capabilities: { edit: true, copy: true, test: true, toggle: true, delete: true, export: true },
    })
    const listRules = vi.fn()
      .mockResolvedValueOnce(ok({ items: [], total: 0 }))
      .mockResolvedValueOnce(ok({ items: [imported], total: 1 }))
    const confirmImport = vi.fn(async () => ok({ importedQualifiedIds: ['user:fresh'], skippedCount: 0, generation: 6 }))
    const bridge = createMockBridge({
      list_rules: listRules,
      async begin_rule_import() {
        return ok({
          cancelled: false as const, sessionId: 'session-1',
          items: [{
            itemId: 'fresh', fileName: 'fresh.yaml', valid: true, errors: [],
            qualifiedId: 'user:fresh', ruleType: 'engine', status: 'experimental',
            conflict: 'none', allowedDecisions: ['import', 'skip'],
          }],
        })
      },
      confirm_rule_import: confirmImport,
      async get_rule() { return ok(imported) },
    })
    const wrapper = mount(RuleManagementWorkspace, {
      attachTo: document.body,
      props: { bridge },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()
    const importEntry = wrapper.findAll('button').find((button) => button.text() === '导入规则')!
    await importEntry.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="rule-import-dialog"]').exists()).toBe(true)
    await wrapper.get('[data-test="confirm-rule-import"]').trigger('click')
    await flushPromises()

    expect(confirmImport).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-test="rule-import-dialog"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Fresh')
    expect(document.activeElement).toBe(importEntry.element)
    wrapper.unmount()
  })
})
