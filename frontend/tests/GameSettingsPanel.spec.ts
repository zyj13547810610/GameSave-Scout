import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMockBridge, fixtureGame, ok } from '../src/api/mockBridge'
import GameSettingsPanel from '../src/features/library/GameSettingsPanel.vue'

enableAutoUnmount(afterEach)
afterEach(() => vi.useRealTimers())

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

  it('polls reanalysis to completion without clearing unsaved metadata', async () => {
    vi.useFakeTimers()
    const updated = fixtureGame({ mainExeRelpath: 'Alice.exe', exeArch: 'x64' })
    const start = vi.fn(async () => ok({ taskId: 'reanalyze-1' }))
    const snapshot = vi.fn()
      .mockResolvedValueOnce(ok({
        id: 'reanalyze-1', kind: 'game_reanalysis', status: 'running' as const,
        progress: { completed: 0, total: 1 }, message: '正在重新检测主程序和引擎…',
        details: {}, result: null, error: null,
      }))
      .mockResolvedValueOnce(ok({
        id: 'reanalyze-1', kind: 'game_reanalysis', status: 'completed' as const,
        progress: { completed: 1, total: 1 }, message: '重新检测完成。',
        details: {}, result: updated, error: null,
      }))
    const wrapper = mount(GameSettingsPanel, {
      props: {
        game: fixtureGame({ version: 'v1.0' }),
        bridge: createMockBridge({ start_game_reanalysis: start, task_snapshot: snapshot }),
      },
    })
    await wrapper.get('[data-test="game-title-input"]').setValue('尚未保存的标题')
    await wrapper.get('[data-test="game-version-input"]').setValue('尚未保存的版本')

    await wrapper.get('[data-test="reanalyze-game"]').trigger('click')
    await flushPromises()

    expect(start).toHaveBeenCalledWith({ gameId: 'game-1' })
    expect(wrapper.get('[data-test="reanalyze-game"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="reanalysis-message"]').text()).toContain('正在重新检测')
    await vi.advanceTimersByTimeAsync(350)
    await flushPromises()

    expect(wrapper.emitted('updated')).toEqual([[updated]])
    await wrapper.setProps({ game: updated })
    expect((wrapper.get('[data-test="game-title-input"]').element as HTMLInputElement).value)
      .toBe('尚未保存的标题')
    expect((wrapper.get('[data-test="game-version-input"]').element as HTMLInputElement).value)
      .toBe('尚未保存的版本')
  })

  it.each([
    ['failed', '检测任务失败'],
    ['cancelled', '重新检测已取消。'],
  ] as const)('keeps the old game when reanalysis is %s', async (status, expectedMessage) => {
    const game = fixtureGame({ mainExeRelpath: 'Old.exe' })
    const wrapper = mount(GameSettingsPanel, {
      props: {
        game,
        bridge: createMockBridge({
          async start_game_reanalysis() { return ok({ taskId: 'reanalyze-1' }) },
          async task_snapshot() {
            return ok({
              id: 'reanalyze-1', kind: 'game_reanalysis', status,
              progress: { completed: 0, total: 1 }, message: '', details: {}, result: null,
              error: status === 'failed'
                ? { code: 'task_failed', message: '检测任务失败' }
                : null,
            })
          },
        }),
      },
    })

    await wrapper.get('[data-test="reanalyze-game"]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('updated')).toBeUndefined()
    expect(wrapper.get('[data-test="reanalysis-error"]').text()).toContain(expectedMessage)
    expect(wrapper.text()).toContain('Old.exe')
  })

  it('rejects an invalid completed task result', async () => {
    const wrapper = mount(GameSettingsPanel, {
      props: {
        game: fixtureGame(),
        bridge: createMockBridge({
          async start_game_reanalysis() { return ok({ taskId: 'reanalyze-1' }) },
          async task_snapshot() {
            return ok({
              id: 'reanalyze-1', kind: 'game_reanalysis', status: 'completed',
              progress: { completed: 1, total: 1 }, message: '完成', details: {},
              result: { id: 'game-1' }, error: null,
            })
          },
        }),
      },
    })

    await wrapper.get('[data-test="reanalyze-game"]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('updated')).toBeUndefined()
    expect(wrapper.get('[data-test="reanalysis-error"]').text()).toContain('无效结果')
  })

  it('rejects a completed task result with malformed group ids', async () => {
    const invalid = { ...fixtureGame(), groupIds: ['group-rpg', 1] }
    const wrapper = mount(GameSettingsPanel, {
      props: {
        game: fixtureGame(),
        bridge: createMockBridge({
          async start_game_reanalysis() { return ok({ taskId: 'reanalyze-1' }) },
          async task_snapshot() {
            return ok({
              id: 'reanalyze-1', kind: 'game_reanalysis', status: 'completed',
              progress: { completed: 1, total: 1 }, message: '完成', details: {},
              result: invalid, error: null,
            })
          },
        }),
      },
    })

    await wrapper.get('[data-test="reanalyze-game"]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('updated')).toBeUndefined()
    expect(wrapper.get('[data-test="reanalysis-error"]').text()).toContain('无效结果')
  })

  it('cancels an active reanalysis task', async () => {
    vi.useFakeTimers()
    const cancel = vi.fn(async () => ok({ cancelled: true }))
    const wrapper = mount(GameSettingsPanel, {
      props: {
        game: fixtureGame(),
        bridge: createMockBridge({
          async start_game_reanalysis() { return ok({ taskId: 'reanalyze-1' }) },
          async task_snapshot() {
            return ok({
              id: 'reanalyze-1', kind: 'game_reanalysis', status: 'running',
              progress: { completed: 0, total: 1 }, message: '正在检测',
              details: {}, result: null, error: null,
            })
          },
          cancel_task: cancel,
        }),
      },
    })
    await wrapper.get('[data-test="reanalyze-game"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-test="cancel-reanalysis"]').trigger('click')

    expect(cancel).toHaveBeenCalledWith('reanalyze-1')
  })
})
