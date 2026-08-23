import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RuleListPane from '../src/features/rules/RuleListPane.vue'

describe('RuleListPane', () => {
  it('shows wrapped rule identity and source/status/type badges', () => {
    const wrapper = mount(RuleListPane, {
      props: {
        items: [{
          qualifiedId: 'builtin:very-long-rule-id',
          ruleId: 'very-long-rule-id',
          label: '一个很长很长但不能与下一条规则重叠的规则名称',
          ruleType: 'save_engine', source: 'builtin', status: 'experimental',
          enabled: false, priority: 10,
        }],
        selectedQualifiedId: null,
        loading: false,
      },
    })

    expect(wrapper.text()).toContain('内置规则')
    expect(wrapper.text()).toContain('实验')
    expect(wrapper.text()).toContain('引擎存档')
    expect(wrapper.text()).toContain('已停用')
    expect(wrapper.get('.rule-list-label').attributes('title')).toBeUndefined()
  })

  it('focuses the requested neighboring rule after deletion', async () => {
    const item = {
      qualifiedId: 'user:next', ruleId: 'next', label: 'Next', ruleType: 'engine' as const,
      source: 'user' as const, status: 'experimental' as const, enabled: true, priority: 10,
    }
    const wrapper = mount(RuleListPane, {
      attachTo: document.body,
      props: { items: [item], selectedQualifiedId: item.qualifiedId, focusQualifiedId: null, loading: false },
    })
    await wrapper.setProps({ focusQualifiedId: item.qualifiedId })
    await flushPromises()

    expect(document.activeElement).toBe(wrapper.get('.rule-list-item').element)
    expect(wrapper.emitted('focused')).toHaveLength(1)
    wrapper.unmount()
  })
})
