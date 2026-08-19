import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMockBridge, fixtureGroup, ok } from '../src/api/mockBridge'
import BatchGroupDialog from '../src/features/library/BatchGroupDialog.vue'

describe('BatchGroupDialog', () => {
  it('submits one selected group and mode for the selected games', async () => {
    const result = { addedCount: 0, removedCount: 2, unchangedCount: 1 }
    const update = vi.fn(async () => ok(result))
    const wrapper = mount(BatchGroupDialog, {
      props: {
        open: true,
        groups: [
          fixtureGroup({ id: 'group-rpg', name: 'RPG' }),
          fixtureGroup({ id: 'group-slg', name: 'SLG' }),
        ],
        selectedGameIds: ['game-1', 'game-2', 'game-3'],
        bridge: createMockBridge({ update_game_group_memberships: update }),
      },
    })

    expect(wrapper.get('[data-test="confirm-batch-group"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="batch-group-select"]').setValue('group-slg')
    await wrapper.get('[data-test="batch-group-mode-remove"]').setValue(true)
    await wrapper.get('[data-test="batch-group-form"]').trigger('submit')
    await flushPromises()

    expect(update).toHaveBeenCalledWith({
      groupId: 'group-slg',
      gameIds: ['game-1', 'game-2', 'game-3'],
      mode: 'remove',
    })
    expect(wrapper.emitted('applied')).toEqual([[result]])
  })

  it('does not submit more than 500 raw game ids', async () => {
    const update = vi.fn(async () => ok({ addedCount: 0, removedCount: 0, unchangedCount: 0 }))
    const wrapper = mount(BatchGroupDialog, {
      props: {
        open: true,
        groups: [fixtureGroup()],
        selectedGameIds: Array.from({ length: 501 }, (_, index) => `game-${index}`),
        bridge: createMockBridge({ update_game_group_memberships: update }),
      },
    })

    await wrapper.get('[data-test="batch-group-select"]').setValue('group-1')
    expect(wrapper.get('[data-test="confirm-batch-group"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('一次最多调整 500 个游戏')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(update).not.toHaveBeenCalled()
  })

  it('keeps the dialog, group and mode after a failed update', async () => {
    const wrapper = mount(BatchGroupDialog, {
      props: {
        open: true,
        groups: [fixtureGroup({ id: 'group-rpg' })],
        selectedGameIds: ['game-1'],
        bridge: createMockBridge({
          async update_game_group_memberships() {
            return { ok: false, error: { code: 'failed', message: '批量调整失败' } }
          },
        }),
      },
    })

    await wrapper.get('[data-test="batch-group-select"]').setValue('group-rpg')
    await wrapper.get('[data-test="batch-group-mode-remove"]').setValue(true)
    await wrapper.get('[data-test="batch-group-form"]').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[data-test="batch-group-dialog"]').exists()).toBe(true)
    expect((wrapper.get('[data-test="batch-group-select"]').element as HTMLSelectElement).value).toBe('group-rpg')
    expect((wrapper.get('[data-test="batch-group-mode-remove"]').element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.get('[role="alert"]').text()).toContain('批量调整失败')
    expect(wrapper.emitted('applied')).toBeUndefined()
  })

  it('offers group management when no groups exist', async () => {
    const wrapper = mount(BatchGroupDialog, {
      props: {
        open: true,
        groups: [],
        selectedGameIds: ['game-1'],
        bridge: createMockBridge(),
      },
    })

    expect(wrapper.text()).toContain('还没有分组')
    await wrapper.get('[data-test="manage-groups-from-batch"]').trigger('click')
    expect(wrapper.emitted('manageGroups')).toHaveLength(1)
  })
})
