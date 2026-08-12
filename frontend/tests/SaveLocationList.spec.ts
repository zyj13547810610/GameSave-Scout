import { enableAutoUnmount, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SaveLocation } from '../src/api/contracts'
import { createMockBridge } from '../src/api/mockBridge'
import SaveLocationList from '../src/features/saves/SaveLocationList.vue'

enableAutoUnmount(afterEach)

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
})
