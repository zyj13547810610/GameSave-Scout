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

  it('saves title and version together after trimming both fields', async () => {
    const saveMetadata = vi.fn(async () => ok(fixtureGame({
      title: '自定义标题',
      version: 'Ver 2.0',
    })))
    const wrapper = mount(GameSettingsPanel, {
      props: {
        game: fixtureGame({ version: 'v1.0' }),
        bridge: createMockBridge({ set_game_metadata: saveMetadata }),
      },
    })

    await wrapper.get('[data-test="game-title-input"]').setValue('  自定义标题  ')
    await wrapper.get('[data-test="game-version-input"]').setValue('  Ver 2.0  ')
    await wrapper.get('[data-test="save-game-metadata"]').trigger('click')

    expect(saveMetadata).toHaveBeenCalledWith({
      gameId: 'game-1',
      title: '自定义标题',
      version: 'Ver 2.0',
    })
  })

  it('sends an empty version as null', async () => {
    const saveMetadata = vi.fn(async () => ok(fixtureGame({ version: null })))
    const wrapper = mount(GameSettingsPanel, {
      props: {
        game: fixtureGame({ version: 'v1.0' }),
        bridge: createMockBridge({ set_game_metadata: saveMetadata }),
      },
    })

    await wrapper.get('[data-test="game-version-input"]').setValue('   ')
    await wrapper.get('[data-test="save-game-metadata"]').trigger('click')

    expect(saveMetadata).toHaveBeenCalledWith({
      gameId: 'game-1',
      title: 'Alice',
      version: null,
    })
  })

  it('keeps both edited values when the atomic save fails', async () => {
    const wrapper = mount(GameSettingsPanel, {
      props: {
        game: fixtureGame({ version: 'v1.0' }),
        bridge: createMockBridge({
          set_game_metadata: async () => ({
            ok: false,
            error: { code: 'invalid_request', message: '保存失败' },
          }),
        }),
      },
    })

    await wrapper.get('[data-test="game-title-input"]').setValue('编辑中的标题')
    await wrapper.get('[data-test="game-version-input"]').setValue('编辑中的版本')
    await wrapper.get('[data-test="save-game-metadata"]').trigger('click')

    expect((wrapper.get('[data-test="game-title-input"]').element as HTMLInputElement).value)
      .toBe('编辑中的标题')
    expect((wrapper.get('[data-test="game-version-input"]').element as HTMLInputElement).value)
      .toBe('编辑中的版本')
    expect(wrapper.text()).toContain('保存失败')
  })
})
