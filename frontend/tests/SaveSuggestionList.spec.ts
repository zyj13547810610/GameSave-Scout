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
    availability: 'found',
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

    await wrapper.get('[data-test="find-save-suggestions"]').trigger('click')
    await flushPromises()
    expect(suggest).toHaveBeenCalledTimes(2)
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

  it('shows found items first and keeps predicted items collapsed by default', () => {
    const wrapper = mount(SaveSuggestionList, {
      props: {
        gameId: 'game-1',
        suggestions: [
          fixtureSuggestion({
            suggestionId: 'predicted',
            displayPath: 'C:\\Predicted',
            availability: 'predicted',
            preselected: true,
          }),
          fixtureSuggestion({
            suggestionId: 'found',
            displayPath: 'C:\\Found',
            availability: 'found',
          }),
        ],
        bridge: createMockBridge(),
      },
    })

    const groups = wrapper.findAll('.suggestion-group')
    expect(groups[0].text()).toContain('已找到')
    expect(groups[0].text()).toContain('C:\\Found')
    const predicted = wrapper.get('[data-test="predicted-group"]')
    expect(predicted.attributes('open')).toBeUndefined()
    expect(predicted.get('summary').text()).toBe('可能路径 / 未发现（1）')
    expect((wrapper.get('[data-test="suggestion-predicted"]').element as HTMLInputElement).checked).toBe(false)
  })

  it('shows experimental confidence and all merged evidence sources', () => {
    const wrapper = mount(SaveSuggestionList, {
      props: {
        gameId: 'game-1',
        suggestions: [fixtureSuggestion({
          group: 'experimental',
          sourceEvidence: [
            { source: 'user', detail: '用户规则' },
            { source: 'builtin', detail: '内置规则' },
            { source: 'ludusavi', detail: '清单规则' },
            { source: 'engine', detail: '引擎元数据' },
          ],
        })],
        bridge: createMockBridge(),
      },
    })

    expect(wrapper.text()).toContain('实验性')
    expect(wrapper.text()).toContain('用户规则：用户规则')
    expect(wrapper.text()).toContain('内置规则：内置规则')
    expect(wrapper.text()).toContain('Ludusavi：清单规则')
    expect(wrapper.text()).toContain('引擎规则：引擎元数据')
  })

  it('keeps selected suggestions visible when accepting fails', async () => {
    const wrapper = mount(SaveSuggestionList, {
      props: {
        gameId: 'game-1',
        suggestions: [fixtureSuggestion()],
        bridge: createMockBridge({
          async accept_save_suggestions() {
            return { ok: false, error: { code: 'write_failed', message: '保存失败' } }
          },
        }),
      },
    })

    await wrapper.get('[data-test="suggestion-s1"]').setValue(true)
    await wrapper.get('[data-test="accept-selected"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="suggestion-s1"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('保存失败')
  })
})
