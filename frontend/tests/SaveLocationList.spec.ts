import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SaveLocation } from '../src/api/contracts'
import { createMockBridge } from '../src/api/mockBridge'
import SaveLocationList from '../src/features/saves/SaveLocationList.vue'

enableAutoUnmount(afterEach)
beforeEach(() => setActivePinia(createPinia()))

function fixtureSave(overrides: Partial<SaveLocation> = {}): SaveLocation {
  return {
    id: 'save-1',
    gameId: 'game-1',
    kind: 'directory',
    pathTemplate: '<home>\\Saves',
    displayPath: 'C:\\Users\\Alice\\Saves',
    source: 'manual',
    confidence: 1,
    evidence: ['用户手动添加'],
    confirmed: true,
    enabled: true,
    lastVerifiedAt: null,
    exists: true,
    matchCount: null,
    matchesTruncated: false,
    ...overrides,
  }
}

describe('SaveLocationList', () => {
  it('is open by default and opens a confirmed location from its path', async () => {
    const openLocation = vi.fn(async () => ({
      ok: true as const,
      data: { opened: true },
    }))
    const wrapper = mount(SaveLocationList, {
      props: {
        gameId: 'game-1',
        bridge: createMockBridge({ open_save_location: openLocation }),
        locations: [fixtureSave()],
      },
    })

    const section = wrapper.get('[data-test="save-locations-section"]')
    expect((section.element as HTMLDetailsElement).open).toBe(true)
    await wrapper.get('[data-test="save-display-path"]').trigger('click')

    expect(openLocation).toHaveBeenCalledWith({ locationId: 'save-1' })
  })

  it('labels the verify action as verifying all locations', () => {
    const wrapper = mount(SaveLocationList, {
      props: {
        gameId: 'game-1',
        bridge: createMockBridge(),
        locations: [],
      },
    })

    expect(wrapper.text()).toContain('全部验证')
  })

  it('renders multiple locations with source and missing state', () => {
    const wrapper = mount(SaveLocationList, {
      props: {
        gameId: 'game-1',
        bridge: createMockBridge(),
        locations: [
          fixtureSave({ id: '1', source: 'manual', exists: true }),
          fixtureSave({ id: '2', source: 'engine', exists: false, confirmed: true }),
        ],
      },
    })

    expect(wrapper.findAll('[data-test="save-location"]')).toHaveLength(2)
    expect(wrapper.text()).toContain('手动添加')
    expect(wrapper.text()).toContain('当前位置不存在')
  })

  it('confirms before removing a location', async () => {
    const remove = vi.fn(async () => ({ ok: true as const, data: { removed: true } }))
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const wrapper = mount(SaveLocationList, {
      props: {
        gameId: 'game-1',
        bridge: createMockBridge({ remove_save_location: remove }),
        locations: [fixtureSave()],
      },
    })

    await wrapper.get('[data-test="remove-save-location"]').trigger('click')

    expect(remove).not.toHaveBeenCalled()
  })

  it('shows compact rule links and emits game-rule and Ludusavi intents', async () => {
    const update = vi.fn(async () => ({ ok: true as const, data: { taskId: 'unused' } }))
    const wrapper = mount(SaveLocationList, {
      props: {
        gameId: 'game-1',
        bridge: createMockBridge({ update_ludusavi: update }),
        locations: [],
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Ludusavi：随包规则可用')
    expect(update).not.toHaveBeenCalled()
    await wrapper.get('[data-test="create-game-save-rule"]').trigger('click')
    await wrapper.get('[data-test="manage-ludusavi-rules"]').trigger('click')
    expect(wrapper.emitted('create-game-rule')).toHaveLength(1)
    expect(wrapper.emitted('open-ludusavi')).toHaveLength(1)
    expect(wrapper.find('.ludusavi-settings').exists()).toBe(false)
  })
})
