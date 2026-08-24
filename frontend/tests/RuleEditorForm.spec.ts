import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { EngineRuleDraft, RuleDraftValidation } from '../src/api/contracts'
import RuleEditorForm from '../src/features/rules/RuleEditorForm.vue'

const draft: EngineRuleDraft = {
  version: '1', id: 'kiri', label: 'KiriKiri', type: 'engine', status: 'formal',
  priority: 100, enabled: true, notes: null, references: [], variant: '2/Z',
  threshold: .7, all: [{ op: 'path_exists', path: 'data.xp3', weight: 1 }],
  any: [], negative: [],
}

const validation: RuleDraftValidation = {
  valid: true, normalizedDraft: draft, yamlPreview: 'version: "1"\nrules:\n  - id: kiri',
  errorCode: null, message: '规则草稿有效。',
}

describe('RuleEditorForm', () => {
  it('keeps builtin fields read-only and renders backend YAML as plain text', () => {
    const wrapper = mount(RuleEditorForm, {
      props: { draft, mode: 'readonly', validation, busy: false, dirty: false },
    })

    expect(wrapper.findAll('input').every((input) => input.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.findAll('select').every((select) => select.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(wrapper.get('[data-test="rule-yaml-preview"]').text()).toContain('rules:')
    expect(wrapper.html()).not.toContain('contenteditable')
  })

  it('debounces validation by 200ms and only enables save for a valid dirty draft', async () => {
    vi.useFakeTimers()
    const wrapper = mount(RuleEditorForm, {
      props: { draft, mode: 'edit', validation, busy: false, dirty: true },
    })
    await wrapper.get('input[name="label"]').setValue('KiriKiri Z')
    expect(wrapper.emitted('validate')).toBeUndefined()
    await vi.advanceTimersByTimeAsync(199)
    expect(wrapper.emitted('validate')).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(wrapper.emitted('validate')).toHaveLength(1)
    expect(wrapper.get('[data-test="save-rule"]').attributes('disabled')).toBeUndefined()
    vi.useRealTimers()
  })

  it('uses an explicit enabled status select instead of an ambiguous checkbox', async () => {
    const wrapper = mount(RuleEditorForm, {
      props: { draft, mode: 'edit', validation, busy: false, dirty: false },
    })

    expect(wrapper.find('input[name="enabled"]').exists()).toBe(false)
    const enabled = wrapper.get('select[name="enabled"]')
    expect((enabled.element as HTMLSelectElement).value).toBe('enabled')
    await enabled.setValue('disabled')
    expect(wrapper.emitted('update:draft')?.at(-1)?.[0]).toMatchObject({ enabled: false })
  })

  it('shows backend validation failure and disables save without dropping the draft', async () => {
    const invalid: RuleDraftValidation = {
      valid: false, normalizedDraft: null, yamlPreview: null,
      errorCode: 'invalid_rule_draft', message: '至少需要一项证据。',
    }
    const wrapper = mount(RuleEditorForm, {
      props: { draft, mode: 'edit', validation: invalid, busy: false, dirty: true },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('invalid_rule_draft')
    expect(wrapper.text()).toContain('至少需要一项证据')
    expect(wrapper.get('[data-test="save-rule"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('input[name="label"]').element.getAttribute('value')).toBe('KiriKiri')
  })
})
