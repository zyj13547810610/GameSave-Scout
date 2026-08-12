import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMockBridge, fixtureGame } from '../src/api/mockBridge'
import GameDetailDrawer from '../src/features/library/GameDetailDrawer.vue'

describe('GameDetailDrawer', () => {
  it('uses the full original cover and closes on Escape', async () => {
    const wrapper = mount(GameDetailDrawer, {
      props: {
        game: fixtureGame({ coverOriginalUrl: '/cover/original' }),
        bridge: createMockBridge(),
      },
      attachTo: document.body,
    })

    expect(wrapper.get('[data-test="detail-cover"]').attributes('src')).toBe('/cover/original')
    await wrapper.trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
