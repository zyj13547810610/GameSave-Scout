import { enableAutoUnmount, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMockBridge, fixtureGame, ok } from '../src/api/mockBridge'
import GameSettingsPanel from '../src/features/library/GameSettingsPanel.vue'

enableAutoUnmount(afterEach)

describe('GameSettingsPanel', () => {
  it('is open by default and keeps install and executable paths', () => {
    const wrapper = mount(GameSettingsPanel, {
      props: {
        game: fixtureGame({
          installPath: 'D:\\Games\\Alice',
          mainExeRelpath: 'bin/Alice.exe',
        }),
        bridge: createMockBridge(),
      },
    })

    const section = wrapper.get('[data-test="game-settings-section"]')
    expect((section.element as HTMLDetailsElement).open).toBe(true)
    expect(wrapper.text()).toContain('D:\\Games\\Alice')
    expect(wrapper.text()).toContain('bin/Alice.exe')
  })

  it('opens the install path from the path control', async () => {
    const openInstall = vi.fn(async () => ok({ opened: true }))
    const wrapper = mount(GameSettingsPanel, {
      props: {
        game: fixtureGame(),
        bridge: createMockBridge({ open_install_directory: openInstall }),
      },
    })

    await wrapper.get('[data-test="install-path"]').trigger('click')

    expect(openInstall).toHaveBeenCalledWith({ gameId: 'game-1' })
  })
})
