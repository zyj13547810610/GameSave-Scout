import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import type { GameShelfBridge } from '../src/api/contracts'
import { createMockBridge, fixtureGame, ok } from '../src/api/mockBridge'
import GameGrid from '../src/features/library/GameGrid.vue'
import '../src/features/library/library.css'

describe('GameGrid', () => {
  it('opens a right-side drawer without replacing the grid', async () => {
    const wrapper = mount(GameGrid, {
      props: { games: [fixtureGame({ id: '1' })], bridge: createMockBridge() },
    })

    await wrapper.get('[data-test="game-card-1"]').trigger('click')
    expect(wrapper.emitted('update:selectedGameId')).toEqual([['1']])
    await wrapper.setProps({ selectedGameId: '1' })

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
    await wrapper.setProps({ selectedGameId: '1' })
    await wrapper.get('[data-test="drawer-backdrop"]').trigger('click')
    await wrapper.setProps({ selectedGameId: null })
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
    const wrapper = mount(GameGrid, {
      props: { games: [game], bridge, selectedGameId: game.id },
    })

    await wrapper.get('[data-test="delete-missing-game"]').trigger('click')
    await wrapper.setProps({ selectedGameId: null })

    expect(wrapper.find('[data-test="game-detail-drawer"]').exists()).toBe(false)
    expect(wrapper.emitted('removed')).toEqual([[game.id]])
  })

  it('shows version separately on the card and in the selected detail title', async () => {
    const game = fixtureGame({ id: 'versioned', title: 'AoiChan', version: 'v1.0.8' })
    const wrapper = mount(GameGrid, {
      props: { games: [game], bridge: createMockBridge() },
    })

    expect(wrapper.get('.game-version').text()).toBe('v1.0.8')
    expect(wrapper.get('[data-test="game-card-versioned"] strong').text()).toBe('AoiChan')
    await wrapper.setProps({ selectedGameId: game.id })

    expect(wrapper.get('.detail-version-badge').text()).toBe('v1.0.8')
    expect(wrapper.get('.detail-title-row h2').text()).toBe('AoiChan')
  })

  it('does not render empty version placeholders', async () => {
    const game = fixtureGame({ id: 'plain', version: null })
    const wrapper = mount(GameGrid, {
      props: { games: [game], bridge: createMockBridge(), selectedGameId: game.id },
    })

    expect(wrapper.find('.game-version').exists()).toBe(false)
    expect(wrapper.find('.detail-version-badge').exists()).toBe(false)
  })

  it('keeps long title and version nodes inside flexible layouts', async () => {
    const game = fixtureGame({
      id: 'long',
      title: 'A very long title that must not widen the game card or detail drawer',
      version: 'Version 1234567890.1234567890.1234567890',
    })
    const wrapper = mount(GameGrid, {
      props: { games: [game], bridge: createMockBridge(), selectedGameId: game.id },
      attachTo: document.body,
    })

    expect(getComputedStyle(wrapper.get('.game-version').element).minWidth)
      .toMatch(/^0(?:px)?$/)
    expect(getComputedStyle(wrapper.get('.detail-title-row').element).minWidth)
      .toMatch(/^0(?:px)?$/)
    expect(getComputedStyle(wrapper.get('.detail-version-badge').element).overflowWrap)
      .toBe('anywhere')
    wrapper.unmount()
  })

  it('forwards a rule-management intent while App decides whether the drawer may close', async () => {
    const game = fixtureGame({ id: 'rule-game' })
    const wrapper = mount(GameGrid, {
      props: { games: [game], bridge: createMockBridge(), selectedGameId: game.id },
    })

    await wrapper.get('[data-test="create-game-save-rule"]').trigger('click')

    expect(wrapper.emitted('update:selectedGameId')).toBeUndefined()
    expect(wrapper.emitted('openRules')).toEqual([[{ tab: 'save', gameId: game.id }]])
  })
})
