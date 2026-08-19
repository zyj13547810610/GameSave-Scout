import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMockBridge, fixtureGame, fixtureGroup, ok } from '../src/api/mockBridge'
import GameGroupSection from '../src/features/library/GameGroupSection.vue'

describe('GameGroupSection', () => {
  it('replaces multiple groups in stable list order without mutating the prop', async () => {
    const game = fixtureGame({ groupIds: ['group-rpg'] })
    const groups = [
      fixtureGroup({ id: 'group-rpg', name: 'RPG' }),
      fixtureGroup({ id: 'group-slg', name: 'SLG' }),
    ]
    const updated = fixtureGame({ groupIds: ['group-rpg', 'group-slg'] })
    const save = vi.fn(async () => ok(updated))
    const wrapper = mount(GameGroupSection, {
      props: {
        game,
        groups,
        bridge: createMockBridge({ set_game_groups: save }),
      },
    })

    expect((wrapper.get('[data-test="game-group-group-rpg"]').element as HTMLInputElement).checked).toBe(true)
    await wrapper.get('[data-test="game-group-group-slg"]').setValue(true)
    expect(game.groupIds).toEqual(['group-rpg'])
    await wrapper.get('[data-test="save-game-groups"]').trigger('click')
    await flushPromises()

    expect(save).toHaveBeenCalledWith({
      gameId: game.id,
      groupIds: ['group-rpg', 'group-slg'],
    })
    expect(wrapper.emitted('updated')).toEqual([[updated]])
    expect(wrapper.get('[data-test="save-game-groups"]').attributes('disabled')).toBeDefined()
  })

  it.each(['installed', 'missing', 'save_only'] as const)(
    'keeps the selected groups after a failed save for %s games',
    async (status) => {
      const wrapper = mount(GameGroupSection, {
        props: {
          game: fixtureGame({ status, groupIds: [] }),
          groups: [fixtureGroup({ id: 'group-rpg' })],
          bridge: createMockBridge({
            async set_game_groups() {
              return { ok: false, error: { code: 'failed', message: '保存分组失败' } }
            },
          }),
        },
      })

      await wrapper.get('[data-test="game-group-group-rpg"]').setValue(true)
      await wrapper.get('[data-test="save-game-groups"]').trigger('click')
      await flushPromises()

      expect(wrapper.get('[role="alert"]').text()).toContain('保存分组失败')
      expect((wrapper.get('[data-test="game-group-group-rpg"]').element as HTMLInputElement).checked).toBe(true)
      expect(wrapper.emitted('updated')).toBeUndefined()
    },
  )

  it('offers group management when no groups exist', async () => {
    const wrapper = mount(GameGroupSection, {
      props: {
        game: fixtureGame(),
        groups: [],
        bridge: createMockBridge(),
      },
    })

    expect(wrapper.text()).toContain('还没有分组')
    await wrapper.get('[data-test="manage-groups-from-detail"]').trigger('click')

    expect(wrapper.emitted('manageGroups')).toHaveLength(1)
    expect(wrapper.emitted('manageGroups')?.[0][0]).toBeInstanceOf(MouseEvent)
  })
})
