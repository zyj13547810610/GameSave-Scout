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
    expect(wrapper.get('[data-test="product-id-help"]').text())
      .toContain('steam、gog、epic、itch、vndb、dlsite')
    expect(wrapper.get('[data-test="product-id-help"]').text()).toContain('每项填写一个')
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

  it('edits the location existence mode and offers the RenPy metadata placeholder', async () => {
    const draft: GameSaveRuleDraft = {
      version: '1', id: 'alice', label: 'Alice', type: 'save_game', status: 'experimental',
      priority: 100, enabled: true, notes: null, references: [], titles: ['Alice'], product_ids: [], locations: [location],
    }
    const wrapper = mount(SaveRuleForm, { props: { modelValue: draft, readonly: false } })
    const mode = wrapper.get('[data-test="location-existence-mode"]')

    expect((mode.element as HTMLSelectElement).value).toBe('false')
    expect(mode.findAll('option').map((item) => item.text())).toEqual(['始终建议', '仅找到时显示'])
    expect(wrapper.text()).toContain('{renpy_save_directory}')
    expect(wrapper.text()).toContain('Ren\'Py 安全元数据')

    await mode.setValue('true')
    const emitted = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as GameSaveRuleDraft
    expect(emitted.locations[0]?.require_existing).toBe(true)
  })

  it('creates new locations with an explicit relaxed existence policy', async () => {
    const draft: EngineSaveRuleDraft = {
      version: '1', id: 'unity-save', label: 'Unity Save', type: 'save_engine', status: 'experimental',
      priority: 100, enabled: true, notes: null, references: [], engine_ids: ['unity'], locations: [],
    }
    const wrapper = mount(SaveRuleForm, { props: { modelValue: draft, readonly: false } })

    const addLocation = wrapper.findAll('button').find((item) => item.text() === '添加位置')
    if (!addLocation) throw new Error('missing add location button')
    await addLocation.trigger('click')

    const emitted = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as EngineSaveRuleDraft
    expect(emitted.locations[0]?.require_existing).toBe(false)
  })
})
