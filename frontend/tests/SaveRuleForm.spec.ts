import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { EngineSaveRuleDraft, GameSaveRuleDraft } from '../src/api/contracts'
import SaveRuleForm from '../src/features/rules/SaveRuleForm.vue'

const location = { kind: 'directory' as const, path: '<winDocuments>\\Alice', category: 'save' as const, confidence: .9 }

describe('SaveRuleForm', () => {
  it('requires title selectors for a game rule and offers optional product IDs', () => {
    const draft: GameSaveRuleDraft = {
      version: '1', id: 'alice', label: 'Alice', type: 'save_game', status: 'experimental',
      priority: 100, enabled: true, notes: null, references: [],
      titles: ['Alice'], product_ids: [], locations: [location],
    }
    const wrapper = mount(SaveRuleForm, { props: { modelValue: draft, readonly: false } })

    expect(wrapper.find('[data-test="game-title-selectors"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="product-id-selectors"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="engine-id-selectors"]').exists()).toBe(false)
  })

  it('requires stable engine IDs for an engine save rule', () => {
    const draft: EngineSaveRuleDraft = {
      version: '1', id: 'unity-save', label: 'Unity Save', type: 'save_engine', status: 'experimental',
      priority: 100, enabled: true, notes: null, references: [], engine_ids: ['unity'], locations: [location],
    }
    const wrapper = mount(SaveRuleForm, { props: { modelValue: draft, readonly: false } })

    expect(wrapper.find('[data-test="engine-id-selectors"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="game-title-selectors"]').exists()).toBe(false)
  })

  it('only offers declarative location kinds, categories and safe roots', () => {
    const draft: GameSaveRuleDraft = {
      version: '1', id: 'alice', label: 'Alice', type: 'save_game', status: 'experimental',
      priority: 100, enabled: true, notes: null, references: [], titles: ['Alice'], product_ids: [], locations: [location],
    }
    const wrapper = mount(SaveRuleForm, { props: { modelValue: draft, readonly: false } })

    expect(wrapper.findAll('[data-test="location-kind"] option').map((item) => item.attributes('value')))
      .toEqual(['directory', 'file', 'glob', 'registry'])
    expect(wrapper.findAll('[data-test="location-category"] option').map((item) => item.attributes('value')))
      .toEqual(['save', 'config', 'other'])
    expect(wrapper.findAll('[data-test="location-root"] option').map((item) => item.attributes('value')))
      .toContain('<winLocalAppDataLow>')
    expect(wrapper.find('textarea').exists()).toBe(false)
  })
})
