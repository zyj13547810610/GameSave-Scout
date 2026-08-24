import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { EngineRuleDraft, RuleDetail, RuleDraftValidation } from '../src/api/contracts'
import RuleDetailPane from '../src/features/rules/RuleDetailPane.vue'

const draft: EngineRuleDraft = {
  version: '1', id: 'kiri', label: 'KiriKiri', type: 'engine', status: 'experimental',
  priority: 100, enabled: true, notes: null, references: [], variant: '2/Z',
  threshold: .7, all: [{ op: 'path_exists', path: 'data.xp3', weight: 1 }],
  any: [], negative: [],
}

const validation: RuleDraftValidation = {
  valid: true, normalizedDraft: draft, yamlPreview: 'version: "1"',
  errorCode: null, message: '规则草稿有效。',
}

const detail: RuleDetail = {
  qualifiedId: 'user:kiri', ruleId: 'kiri', label: 'KiriKiri', ruleType: 'engine',
  source: 'user', status: 'experimental', enabled: true, priority: 100,
  notes: null, references: [], sourceFile: 'user/engines/kiri.yaml',
  yamlPreview: 'version: "1"', draft,
  capabilities: { edit: true, copy: true, test: true, toggle: true, delete: true, export: true },
}

describe('RuleDetailPane', () => {
  it('scrolls and focuses the local test panel from the editor shortcut', async () => {
    const scrollIntoView = vi.fn()
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView
    HTMLElement.prototype.scrollIntoView = scrollIntoView
    const wrapper = mount(RuleDetailPane, {
      attachTo: document.body,
      props: {
        detail, draft, validation, testResult: null, games: [], loading: false,
        busy: false, testing: false, dirty: false, canMarkVerified: false,
        error: '', mutationError: '', notice: '',
      },
    })

    await wrapper.get('.rule-editor-actions .secondary').trigger('click')

    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' })
    expect(document.activeElement).toBe(wrapper.get('[data-test="rule-test-anchor"]').element)
    wrapper.unmount()
    HTMLElement.prototype.scrollIntoView = originalScrollIntoView
  })
})
