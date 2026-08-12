import { enableAutoUnmount, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMockBridge, ok } from '../src/api/mockBridge'
import AddSaveLocationDialog from '../src/features/saves/AddSaveLocationDialog.vue'

enableAutoUnmount(afterEach)

describe('AddSaveLocationDialog', () => {
  it('combines the selected directory and glob pattern', async () => {
    const add = vi.fn(async () => ok({ id: 'save-1' } as never))
    const wrapper = mount(AddSaveLocationDialog, {
      props: {
        gameId: 'game-1',
        bridge: createMockBridge({
          choose_save_path: async () => ok('C:\\Saves'),
          add_manual_save_location: add,
        }),
      },
    })

    await wrapper.get('[data-test="save-kind"]').setValue('glob')
    await wrapper.get('[data-test="choose-save-path"]').trigger('click')
    await wrapper.get('[data-test="glob-pattern"]').setValue('slot-*.sav')
    await wrapper.get('form').trigger('submit')

    expect(add).toHaveBeenCalledWith({
      gameId: 'game-1',
      kind: 'glob',
      selectedPath: 'C:\\Saves\\slot-*.sav',
    })
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })

  it('validates registry root syntax before submitting', async () => {
    const add = vi.fn()
    const wrapper = mount(AddSaveLocationDialog, {
      props: {
        gameId: 'game-1',
        bridge: createMockBridge({ add_manual_save_location: add }),
      },
    })
    await wrapper.get('[data-test="save-kind"]').setValue('registry')
    await wrapper.get('[data-test="registry-path"]').setValue('Software\\Studio')

    await wrapper.get('form').trigger('submit')

    expect(add).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('HKEY_CURRENT_USER')
  })
})
