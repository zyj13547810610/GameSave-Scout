import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { GuidedSavePreview } from '../src/api/contracts'
import { createMockBridge, fixtureGuidedSession, ok } from '../src/api/mockBridge'
import GuidedSavePanel from '../src/features/saves/GuidedSavePanel.vue'
import { useGuidedSaveStore } from '../src/features/saves/guidedSaveStore'

beforeEach(() => setActivePinia(createPinia()))

describe('GuidedSavePanel', () => {
  it('previews only after a click and starts with the approved scope IDs', async () => {
    const preview = vi.fn(async () => ok(fixturePreview()))
    const session = fixtureGuidedSession({ id: 'session-1' })
    const start = vi.fn(async () => ok(session))
    const bridge = createMockBridge({
      preview_guided_save_detection: preview,
      start_guided_save_detection: start,
      async guided_save_detection_status() { return ok(session) },
    })
    const wrapper = mount(GuidedSavePanel, {
      props: { gameId: 'game-1', bridge },
    })
    await flushPromises()

    expect(preview).not.toHaveBeenCalled()
    expect(start).not.toHaveBeenCalled()
    await wrapper.get('[data-test="open-guided-preview"]').trigger('click')
    await flushPromises()

    expect(preview).toHaveBeenCalledWith({ gameId: 'game-1' })
    expect((wrapper.get('[data-test="guided-scope-default:game"]').element as HTMLInputElement).checked).toBe(true)
    expect((wrapper.get('[data-test="guided-scope-default:program-data"]').element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.get('[data-test="guided-scope-default:saved-games"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('不读取或修改存档内容')

    await wrapper.get('[data-test="confirm-guided-start"]').trigger('click')
    await flushPromises()

    expect(start).toHaveBeenCalledWith({
      gameId: 'game-1',
      selectedScopeIds: ['default:game'],
      additionalDirectories: [],
    })
  })

  it('shows monitoring commands and locks them while settling', async () => {
    const store = useGuidedSaveStore()
    store.session = fixtureGuidedSession({ status: 'monitoring' })
    const wrapper = mount(GuidedSavePanel, {
      props: { gameId: 'game-1', bridge: createMockBridge() },
    })
    await flushPromises()

    expect(wrapper.find('[data-test="guided-mark-saved"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="guided-stop-analyze"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="guided-cancel"]').exists()).toBe(true)

    store.session = fixtureGuidedSession({ status: 'settling' })
    await flushPromises()
    expect(wrapper.text()).toContain('约 3 秒')
    expect(wrapper.find('[data-test="guided-mark-saved"]').exists()).toBe(false)
  })

  it('warns without stopping commands when process tracking degrades', async () => {
    const store = useGuidedSaveStore()
    store.session = fixtureGuidedSession({
      status: 'monitoring',
      processTrackingDegraded: true,
    })
    const wrapper = mount(GuidedSavePanel, {
      props: { gameId: 'game-1', bridge: createMockBridge() },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('无法可靠判断游戏是否仍在运行')
    expect(wrapper.find('[data-test="guided-mark-saved"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="guided-stop-analyze"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="guided-cancel"]').exists()).toBe(true)
  })

  it('keeps the entry visible but disabled while another game is active', async () => {
    const store = useGuidedSaveStore()
    store.session = fixtureGuidedSession({ gameId: 'other', gameTitle: 'Bob' })
    const wrapper = mount(GuidedSavePanel, {
      props: { gameId: 'game-1', bridge: createMockBridge() },
    })
    await flushPromises()

    expect(wrapper.get('[data-test="open-guided-preview"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('正在为《Bob》寻找存档')
  })
})

function fixturePreview(): GuidedSavePreview {
  return {
    gameId: 'game-1',
    gameTitle: 'Alice',
    executable: 'D:\\Games\\Alice\\Alice.exe',
    scopes: [
      {
        id: 'default:game', label: '游戏安装目录', displayPath: 'D:\\Games\\Alice',
        pathTemplate: '<game>', source: 'game', defaultSelected: true,
        available: true, unavailableReason: null,
      },
      {
        id: 'default:program-data', label: 'ProgramData', displayPath: 'C:\\ProgramData',
        pathTemplate: '<winProgramData>', source: 'program_data', defaultSelected: false,
        available: true, unavailableReason: null,
      },
      {
        id: 'default:saved-games', label: 'Saved Games', displayPath: 'C:\\Saved Games',
        pathTemplate: '<winSavedGames>', source: 'saved_games', defaultSelected: true,
        available: false, unavailableReason: '目录不存在或无法访问。',
      },
    ],
    registryTargets: [],
    privacyNotice: '只读取文件路径、大小和修改时间等元数据，不读取或修改存档内容。',
  }
}
