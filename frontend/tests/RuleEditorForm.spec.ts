import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { EngineRuleDraft, RuleDraftValidation } from '../src/api/contracts'
import RuleEditorForm from '../src/features/rules/RuleEditorForm.vue'

const draft: EngineRuleDraft = {
  version: '1', id: 'kiri', label: 'KiriKiri', type: 'engine', status: 'formal',
  priority: 100, enabled: true, notes: null, references: [], variant: '2/Z', category: 'visual_novel_doujin',
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

  it('requires a category for a newly created engine rule without guessing general', async () => {
    const unclassified: EngineRuleDraft = { ...draft, category: null }
    const wrapper = mount(RuleEditorForm, {
      props: { draft: unclassified, mode: 'create', validation, busy: false, dirty: true },
    })

    const category = wrapper.get('select[name="category"]')
    expect((category.element as HTMLSelectElement).value).toBe('')
    expect(wrapper.get('[data-test="save-rule"]').attributes('disabled')).toBeDefined()

    await category.setValue('general')
    expect(wrapper.emitted('update:draft')?.at(-1)?.[0]).toMatchObject({ category: 'general' })
  })

  it('shows an old unclassified user rule without forcing a fake category', () => {
    const unclassified: EngineRuleDraft = { ...draft, category: null }
    const wrapper = mount(RuleEditorForm, {
      props: { draft: unclassified, mode: 'edit', validation, busy: false, dirty: true },
    })

    expect(wrapper.get('select[name="category"]').text()).toContain('未分类')
    expect(wrapper.get('[data-test="save-rule"]').attributes('disabled')).toBeUndefined()
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
