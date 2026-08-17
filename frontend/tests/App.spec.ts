import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
import { bridgeKey } from '../src/api/bridge'
import type { ApiResult, Game, GameShelfBridge, UiScaleValue } from '../src/api/contracts'
import { createMockBridge, fixtureGame, fixtureGuidedSession, ok } from '../src/api/mockBridge'
import '../src/styles/base.css'

beforeEach(() => {
  localStorage.clear()
  document.documentElement.style.removeProperty('--ui-scale')
})

describe('App', () => {
  it('keeps the batch entry heading separated from the filters below', async () => {
    const bridge = createMockBridge({
      async list_games() { return ok([fixtureGame()]) },
    })
    const wrapper = mount(App, {
      attachTo: document.body,
      global: {
        plugins: [createPinia()],
        provide: { [bridgeKey as symbol]: bridge },
      },
    })
    await flushPromises()

    expect(getComputedStyle(wrapper.get('.content-heading').element).marginBottom).toBe('1rem')
    wrapper.unmount()
  })

  it('opens the in-app cover workspace while preserving library state', async () => {
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
    const bridge = createMockBridge({
      async list_games() { return ok([fixtureGame()]) },
      async start_cover_wizard() {
        return ok({
          id: 'wizard-1',
          queue: [{
            gameId: 'game-1', title: 'Alice', initialHasCover: false,
            status: 'pending', candidateCount: 0, error: null,
          }],
          currentGameId: 'game-1', includeExisting: false, sourceOperationActive: false,
        })
      },
    })
    const wrapper = mount(App, {
      attachTo: document.body,
      global: {
        plugins: [createPinia()],
        provide: { [bridgeKey as symbol]: bridge },
      },
    })
    await flushPromises()
    await wrapper.get('input[aria-label="搜索游戏"]').setValue('Alice')
    const layout = wrapper.get('.library-layout').element
    const entry = wrapper.get('[data-test="enter-cover-wizard"]')

    await entry.trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="cover-wizard-workspace"]')).toBeTruthy()
    expect(document.body.contains(layout)).toBe(true)
    expect(layout.getAttribute('inert')).not.toBeNull()
    expect(layout.getAttribute('aria-hidden')).toBe('true')

    await wrapper.get('[data-test="cover-wizard-workspace"] [data-autofocus]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="cover-wizard-workspace"]').exists()).toBe(false)
    expect((wrapper.get('input[aria-label="搜索游戏"]').element as HTMLInputElement).value).toBe('Alice')
    expect(document.activeElement).toBe(entry.element)
    expect(scrollTo).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('connects before rendering the empty-library message', async () => {
    const wrapper = mount(App, { global: { plugins: [createPinia()] } })
    expect(wrapper.get('h1').text()).toBe('GameShelf')
    expect(wrapper.text()).toContain('正在连接本地数据库…')

    await flushPromises()

    expect(wrapper.text()).toContain('还没有添加游戏目录')
  })

  it('restores UI scale from bootstrap and persists changes through the bridge', async () => {
    localStorage.setItem('gameshelf.ui-scale', '0.9')
    const setUiScale = vi.fn(async (input: { uiScale: UiScaleValue }) => ok({ uiScale: input.uiScale }))
    const bridge = createMockBridge({
      async bootstrap() {
        return ok({
          appName: 'GameShelf', schemaVersion: 1, portable: true, uiScale: 1.2,
          coverWizardSettings: {
            coverOnlineEnabled: false,
            coverVndbCandidateLimit: 5,
            coverLocalScanCandidateLimit: 10,
          },
        })
      },
      set_ui_scale: setUiScale,
    })
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia()],
        provide: { [bridgeKey as symbol]: bridge },
      },
    })

    await flushPromises()

    expect(document.documentElement.style.getPropertyValue('--ui-scale')).toBe('1.2')
    await wrapper.get('[data-test="ui-scale"]').setValue('0.8')
    await flushPromises()

    expect(document.documentElement.style.getPropertyValue('--ui-scale')).toBe('0.8')
    expect(setUiScale).toHaveBeenCalledWith({ uiScale: 0.8 })
    expect(localStorage.getItem('gameshelf.ui-scale')).toBe('0.9')
  })

  it('keeps the runtime scale and shows a warning when persistence fails', async () => {
    const bridge = createMockBridge({
      async set_ui_scale() {
        return {
          ok: false,
          error: {
            code: 'config_save_failed',
            message: '缩放设置保存失败，下次启动可能恢复默认值。',
          },
        }
      },
    })
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia()],
        provide: { [bridgeKey as symbol]: bridge },
      },
    })
    await flushPromises()

    await wrapper.get('[data-test="ui-scale"]').setValue('0.8')
    await flushPromises()

    expect(document.documentElement.style.getPropertyValue('--ui-scale')).toBe('0.8')
    expect(wrapper.get('[data-test="ui-scale-save-error"]').text()).toBe(
      '缩放设置保存失败，下次启动可能恢复默认值。',
    )
  })

  it('keeps the library grid layout when game details open', async () => {
    const bridge = createMockBridge({
      async list_games() { return ok([fixtureGame({ id: '1' })]) },
    })
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia()],
        provide: { [bridgeKey as symbol]: bridge },
      },
    })
    await flushPromises()
    const layout = wrapper.get('.library-layout').element
    const columnsBefore = getComputedStyle(layout).gridTemplateColumns

    await wrapper.get('[data-test="game-card-1"]').trigger('click')

    expect(layout.querySelector('.settings-panel')).toBeNull()
    expect(getComputedStyle(layout).gridTemplateColumns).toBe(columnsBefore)
  })

  it('restores the monitored game drawer from the global guided status bar', async () => {
    const session = fixtureGuidedSession({ gameId: 'game-1', gameTitle: 'Alice' })
    const bridge = createMockBridge({
      async list_games() { return ok([fixtureGame({ id: 'game-1', title: 'Alice' })]) },
      async current_guided_save_detection() { return ok(session) },
      async guided_save_detection_status() { return ok(session) },
    })
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia()],
        provide: { [bridgeKey as symbol]: bridge },
      },
    })
    await flushPromises()

    expect(wrapper.get('[data-test="guided-save-status-bar"]').text()).toContain('Alice')
    await wrapper.get('[data-test="restore-guided-save"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="game-detail-drawer"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows close choices reported by the guided session', async () => {
    const session = fixtureGuidedSession({ closeRequested: true })
    const resolveClose = vi.fn(async () => ok({ resolved: true }))
    const bridge = createMockBridge({
      async list_games() { return ok([fixtureGame()]) },
      async current_guided_save_detection() { return ok(session) },
      async guided_save_detection_status() { return ok(session) },
      resolve_guided_close: resolveClose,
    })
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia()],
        provide: { [bridgeKey as symbol]: bridge },
      },
    })
    await flushPromises()

    const dialog = wrapper.get('[data-test="guided-save-close-dialog"]')
    await dialog.get('button').trigger('click')
    await flushPromises()

    expect(resolveClose).toHaveBeenCalledWith({ resolution: 'return' })
    wrapper.unmount()
  })

  it('selects eligible games across filters and removes them in one batch', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const games = [
      fixtureGame({ id: 'installed-1', title: 'Alpha', status: 'installed' }),
      fixtureGame({ id: 'missing-1', title: 'Beta', status: 'missing', scanRootId: null }),
      fixtureGame({ id: 'save-1', title: 'Gamma', status: 'save_only', scanRootId: null }),
    ]
    let listCalls = 0
    const removeGames = vi.fn(
      async (_input: Parameters<GameShelfBridge['remove_games']>[0]) => ok({
        installedCount: 1,
        missingCount: 1,
        updatedRootCount: 1,
        cleanupWarnings: ['有 1 个受管封面文件未能清理，可稍后查看日志。'],
      }),
    )
    const bridge = createMockBridge({
      async list_games() {
        listCalls += 1
        return ok(listCalls === 1 ? games : [])
      },
      remove_games: removeGames,
    })
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia()],
        provide: { [bridgeKey as symbol]: bridge },
      },
    })
    await flushPromises()

    await wrapper.get('[data-test="enter-batch-mode"]').trigger('click')
    expect(wrapper.get('[data-test="batch-delete"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="game-card-installed-1"]').trigger('click')
    await wrapper.get('[data-test="game-card-save-1"]').trigger('click')

    expect(wrapper.find('[data-test="game-detail-drawer"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="game-card-save-1"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="batch-counts"]').text()).toContain('已选择 1 个')
    expect(wrapper.get('[data-test="batch-counts"]').text()).toContain('已安装 1')

    await wrapper.get('select[aria-label="状态筛选"]').setValue('missing')
    await wrapper.get('[data-test="select-visible-games"]').trigger('click')

    expect(wrapper.get('[data-test="batch-counts"]').text()).toContain('已选择 2 个')
    expect(wrapper.get('[data-test="batch-counts"]').text()).toContain('失效 1')

    await wrapper.get('[data-test="batch-delete"]').trigger('click')
    await flushPromises()

    expect(removeGames).toHaveBeenCalledWith({
      items: [
        { gameId: 'installed-1', expectedStatus: 'installed' },
        { gameId: 'missing-1', expectedStatus: 'missing' },
      ],
    })
    expect(listCalls).toBe(2)
    expect(wrapper.find('[data-test="batch-management-bar"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="batch-result"]').text()).toContain(
      '已处理 2 个游戏：已安装 1，失效 1；更新 1 个根目录排除项。',
    )
    expect(wrapper.get('[data-test="batch-result"]').text()).toContain(
      '有 1 个受管封面文件未能清理',
    )
  })

  it('cancels batch mode and refreshes when a selected game status changed', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const game = fixtureGame({ id: 'installed-1', status: 'installed' })
    const bridge = createMockBridge({
      async list_games() { return ok([game]) },
      async remove_games() {
        return {
          ok: false,
          error: { code: 'invalid_game_state', message: '游戏状态已经变化。' },
        }
      },
    })
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia()],
        provide: { [bridgeKey as symbol]: bridge },
      },
    })
    await flushPromises()

    await wrapper.get('[data-test="enter-batch-mode"]').trigger('click')
    await wrapper.get('[data-test="game-card-installed-1"]').trigger('click')
    await wrapper.get('[data-test="batch-delete"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="batch-management-bar"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="batch-result"]').text()).toContain(
      '游戏状态已经变化，请重新选择。',
    )
  })

  it('keeps batch submission busy until the successful library refresh finishes', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const game = fixtureGame({ id: 'installed-1', status: 'installed' })
    let listCalls = 0
    let finishReload: ((value: ApiResult<Game[]>) => void) | undefined
    const bridge = createMockBridge({
      async list_games() {
        listCalls += 1
        if (listCalls === 1) return ok([game])
        return new Promise((resolve) => { finishReload = resolve })
      },
      async remove_games() {
        return ok({
          installedCount: 1,
          missingCount: 0,
          updatedRootCount: 1,
          cleanupWarnings: [],
        })
      },
    })
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia()],
        provide: { [bridgeKey as symbol]: bridge },
      },
    })
    await flushPromises()

    await wrapper.get('[data-test="enter-batch-mode"]').trigger('click')
    await wrapper.get('[data-test="game-card-installed-1"]').trigger('click')
    await wrapper.get('[data-test="batch-delete"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="batch-delete"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="batch-delete"]').text()).toBe('处理中…')

    finishReload?.(ok([]))
    await flushPromises()
    expect(wrapper.find('[data-test="batch-management-bar"]').exists()).toBe(false)
  })
})
