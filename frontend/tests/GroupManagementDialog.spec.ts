import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import GroupManagementDialog from '../src/features/library/GroupManagementDialog.vue'
import { createMockBridge, fixtureGroup, ok } from '../src/api/mockBridge'

describe('GroupManagementDialog', () => {
  it('lists counts and creates a trimmed group', async () => {
    const createGroup = vi.fn(async () => ok(fixtureGroup({ id: 'new', name: 'RPG' })))
    const wrapper = mount(GroupManagementDialog, {
      props: {
        bridge: createMockBridge({ create_game_group: createGroup }),
        groups: [fixtureGroup({ name: 'SLG', gameCount: 3 })],
      },
    })

    expect(
      (wrapper.get('[data-test="group-name-group-1"]').element as HTMLInputElement).value,
    ).toBe('SLG')
    expect(wrapper.text()).toContain('3 个游戏')
    await wrapper.get('[data-test="new-group-name"]').setValue('  RPG  ')
    await wrapper.get('[data-test="create-group-form"]').trigger('submit')
    await flushPromises()

    expect(createGroup).toHaveBeenCalledWith({ name: 'RPG' })
    expect(wrapper.emitted('changed')).toHaveLength(1)
    expect((wrapper.get('[data-test="new-group-name"]').element as HTMLInputElement).value).toBe('')
    wrapper.unmount()
  })

  it('renames and confirms deletion without deleting a game', async () => {
    const renameGroup = vi.fn(async () => ok(fixtureGroup({ name: '角色扮演' })))
    const deleteGroup = vi.fn(async () => ok({ deleted: true }))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(GroupManagementDialog, {
      props: {
        bridge: createMockBridge({
          rename_game_group: renameGroup,
          delete_game_group: deleteGroup,
        }),
        groups: [fixtureGroup({ id: 'group-rpg', name: 'RPG' })],
      },
    })

    await wrapper.get('[data-test="group-name-group-rpg"]').setValue('角色扮演')
    await wrapper.get('[data-test="rename-group-group-rpg"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="delete-group-group-rpg"]').trigger('click')
    await flushPromises()

    expect(renameGroup).toHaveBeenCalledWith({ groupId: 'group-rpg', name: '角色扮演' })
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('只会移除分组关系'))
    expect(deleteGroup).toHaveBeenCalledWith({ groupId: 'group-rpg' })
    expect(wrapper.emitted('changed')).toHaveLength(2)
    confirm.mockRestore()
    wrapper.unmount()
  })

  it('keeps the create value and dialog context after a request failure', async () => {
    const wrapper = mount(GroupManagementDialog, {
      props: {
        bridge: createMockBridge({
          async create_game_group() {
            return {
              ok: false,
              error: { code: 'duplicate_game_group', message: '已经存在同名分组。' },
            }
          },
        }),
        groups: [],
      },
    })

    await wrapper.get('[data-test="new-group-name"]').setValue('RPG')
    await wrapper.get('[data-test="create-group-form"]').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('已经存在同名分组')
    expect((wrapper.get('[data-test="new-group-name"]').element as HTMLInputElement).value).toBe('RPG')
    expect(wrapper.find('[data-test="group-management-dialog"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('disables creation at the group limit and closes with Escape', async () => {
    const groups = Array.from({ length: 200 }, (_, index) => fixtureGroup({
      id: `group-${index}`,
      name: `Group ${index}`,
    }))
    const wrapper = mount(GroupManagementDialog, {
      attachTo: document.body,
      props: { bridge: createMockBridge(), groups },
    })

    expect(wrapper.get('[data-test="new-group-name"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('最多创建 200 个分组')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })
})
