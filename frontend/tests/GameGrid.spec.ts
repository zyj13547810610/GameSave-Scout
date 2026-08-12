import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import { createMockBridge, fixtureGame } from '../src/api/mockBridge'
import GameGrid from '../src/features/library/GameGrid.vue'

describe('GameGrid', () => {
  it('opens a right-side drawer without replacing the grid', async () => {
    const wrapper = mount(GameGrid, {
      props: { games: [fixtureGame({ id: '1' })], bridge: createMockBridge() },
    })

    await wrapper.get('[data-test="game-card-1"]').trigger('click')

    expect(wrapper.find('[data-test="game-grid"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="game-detail-drawer"]').exists()).toBe(true)
  })

  it('restores focus to the opening card after backdrop close', async () => {
    const wrapper = mount(GameGrid, {
      props: { games: [fixtureGame({ id: '1' })], bridge: createMockBridge() },
      attachTo: document.body,
    })
    const card = wrapper.get('[data-test="game-card-1"]')

    await card.trigger('click')
    await wrapper.get('[data-test="drawer-backdrop"]').trigger('click')
    await nextTick()

    expect(document.activeElement).toBe(card.element)
    wrapper.unmount()
  })
})
