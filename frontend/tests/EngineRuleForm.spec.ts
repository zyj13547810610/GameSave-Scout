import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { EngineRuleDraft } from '../src/api/contracts'
import EngineRuleForm from '../src/features/rules/EngineRuleForm.vue'

function draft(): EngineRuleDraft {
  return {
    version: '1', id: 'engine', label: 'Engine', type: 'engine', status: 'experimental',
    priority: 100, enabled: true, notes: null, references: [], threshold: .8,
    all: [{ op: 'magic_at', path: 'data.bin', value: 'MAGIC', offset: 0, weight: 1 }],
    any: [], negative: [],
  }
}

describe('EngineRuleForm', () => {
  it('only offers the eight supported evidence operations and their parameters', () => {
    const wrapper = mount(EngineRuleForm, { props: { modelValue: draft(), readonly: false } })
    const options = wrapper.findAll('[data-test="evidence-op"] option').map((item) => item.attributes('value'))

    expect(options).toEqual([
      'path_exists', 'glob_exists', 'glob_magic_at', 'magic_at', 'magic_from_end',
      'edge_contains', 'text_contains', 'pe_field_contains',
    ])
    expect(wrapper.find('[data-test="evidence-value"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="evidence-offset"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="evidence-command"]').exists()).toBe(false)
  })

  it('adds, removes and reorders evidence while enforcing the 64 item cap', async () => {
    const value = draft()
    value.all = Array.from({ length: 64 }, (_, index) => ({
      op: 'path_exists' as const, path: `file-${index}`, weight: 1,
    }))
    const wrapper = mount(EngineRuleForm, { props: { modelValue: value, readonly: false } })

    expect(wrapper.get('[data-test="add-evidence-all"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="remove-evidence-all-0"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toHaveLength(1)
  })
})
