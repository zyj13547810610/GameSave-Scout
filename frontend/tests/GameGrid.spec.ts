import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import type { GameShelfBridge } from '../src/api/contracts'
import { createMockBridge, fixtureGame, ok } from '../src/api/mockBridge'
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

  it('closes the drawer and forwards removal after deleting a record', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const bridge = createMockBridge()
    const remove = vi.fn(async () => ok({ removed: true }))
    ;(bridge as GameShelfBridge & { delete_missing_game: typeof remove }).delete_missing_game = remove
    const game = fixtureGame({ id: 'missing-1', status: 'missing', scanRootId: null })
    const wrapper = mount(GameGrid, { props: { games: [game], bridge } })
    await wrapper.get('[data-test="game-card-missing-1"]').trigger('click')

    await wrapper.get('[data-test="delete-missing-game"]').trigger('click')

    expect(wrapper.find('[data-test="game-detail-drawer"]').exists()).toBe(false)
    expect(wrapper.emitted('removed')).toEqual([[game.id]])
  })
})
