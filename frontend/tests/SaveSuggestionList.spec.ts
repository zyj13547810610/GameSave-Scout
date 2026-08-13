import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SaveSuggestion } from '../src/api/contracts'
import { createMockBridge, ok } from '../src/api/mockBridge'
import SaveSuggestionList from '../src/features/saves/SaveSuggestionList.vue'

enableAutoUnmount(afterEach)

function fixtureSuggestion(overrides: Partial<SaveSuggestion> = {}): SaveSuggestion {
  return {
    suggestionId: 's1',
    kind: 'directory',
    pathTemplate: '<winAppData>\\RenPy\\Alice',
    displayPath: 'C:\\Users\\Alice\\AppData\\Roaming\\RenPy\\Alice',
    source: 'ludusavi',
    confidence: 1,
    evidence: ['标题精确匹配'],
    sourceEvidence: [{ source: 'ludusavi', detail: '标题精确匹配' }],
    preselected: false,
    category: 'save',
    group: 'exact',
    ...overrides,
  }
}

describe('SaveSuggestionList', () => {
  it('only searches for save suggestions after an explicit click', async () => {
    const suggest = vi.fn(async () => ok([fixtureSuggestion()]))
    const wrapper = mount(SaveSuggestionList, {
      props: {
        gameId: 'game-1',
        bridge: createMockBridge({ suggest_save_locations: suggest }),
      },
    })
    await flushPromises()

    expect(suggest).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('点击后才会检查')
    expect(wrapper.get('[data-test="find-save-suggestions"]').text()).toBe('查找存档')

    await wrapper.get('[data-test="find-save-suggestions"]').trigger('click')
    await flushPromises()

    expect(suggest).toHaveBeenCalledTimes(1)
    expect(suggest).toHaveBeenCalledWith({ gameId: 'game-1' })
    expect(wrapper.find('[data-test="suggestion-s1"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="find-save-suggestions"]').text()).toBe('重新查找')
  })

  it('does not persist suggestions until checked and accepted', async () => {
    const accept = vi.fn(async () => ok([]))
    const bridge = createMockBridge({ accept_save_suggestions: accept })
    const wrapper = mount(SaveSuggestionList, {
      props: {
        gameId: 'game-1',
        suggestions: [fixtureSuggestion()],
        bridge,
      },
    })

    await wrapper.get('[data-test="accept-selected"]').trigger('click')
    expect(accept).not.toHaveBeenCalled()
    await wrapper.get('[data-test="suggestion-s1"]').setValue(true)
    await wrapper.get('[data-test="accept-selected"]').trigger('click')

    expect(accept).toHaveBeenCalledWith({
      gameId: 'game-1',
      suggestionIds: ['s1'],
      confirmRegistry: false,
    })
  })

  it('never prechecks registry suggestions', () => {
    const wrapper = mount(SaveSuggestionList, {
      props: {
        gameId: 'game-1',
        suggestions: [fixtureSuggestion({ kind: 'registry', preselected: true })],
        bridge: createMockBridge(),
      },
    })

    expect((wrapper.get('[data-test="suggestion-s1"]').element as HTMLInputElement).checked).toBe(false)
  })
})
