import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'
import { createMockBridge, ok } from '../src/api/mockBridge'
import RuleManagementWorkspace from '../src/features/rules/RuleManagementWorkspace.vue'
import '../src/styles/base.css'

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
})
