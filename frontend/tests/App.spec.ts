import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
import { bridgeKey } from '../src/api/bridge'
import type { ApiResult, Game, GameSaveScoutBridge, UiScaleValue } from '../src/api/contracts'
import { createMockBridge, fixtureGame, fixtureGroup, fixtureGuidedSession, fixtureRoot, ok } from '../src/api/mockBridge'
import { useRuleManagementStore } from '../src/features/rules/ruleManagementStore'
import '../src/styles/base.css'

beforeEach(() => {
  localStorage.clear()
  document.documentElement.style.removeProperty('--ui-scale')
})

describe('App', () => {
  it('keeps four first-level entries in one global header above the workspace', async () => {
    const wrapper = mount(App, {
      attachTo: document.body,
      global: { plugins: [createPinia()], provide: { [bridgeKey as symbol]: createMockBridge() } },
    })
    await flushPromises()

    const shell = wrapper.get('.app-shell')
    const header = wrapper.get('.app-global-header')
    const navigation = header.get('.primary-navigation')
    const libraryLayout = wrapper.get('.library-layout')

    expect(navigation.findAll('button').map((item) => item.text())).toEqual([
      '游戏库',
      '批量存档',
      '批量封面',
      '规则管理',
    ])
    expect(header.element.parentElement).toBe(shell.element)
    expect(getComputedStyle(shell.element).display).toBe('grid')
    expect(getComputedStyle(shell.element).gridTemplateRows).toBe('auto minmax(0, 1fr)')
    expect(getComputedStyle(libraryLayout.element).display).toBe('grid')
    wrapper.unmount()
  })

  it('switches native first-level navigation without cancelling an active scan', async () => {
    const cancel = vi.fn(async () => ok({ cancelled: true }))
    const bridge = createMockBridge({ cancel_task: cancel })
    const wrapper = mount(App, {
      global: { plugins: [createPinia()], provide: { [bridgeKey as symbol]: bridge } },
    })
    await flushPromises()

    expect(wrapper.get('[data-test="nav-library"]').attributes('aria-current')).toBe('page')
    expect(wrapper.find('[data-test="root-scroll-region"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('添加游戏目录')
    expect(wrapper.get('[data-test="nav-batch-saves"]').element.tagName).toBe('BUTTON')

    await wrapper.get('[data-test="nav-batch-saves"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="nav-batch-saves"]').attributes('aria-current')).toBe('page')
    expect(wrapper.find('[data-test="root-scroll-region"]').exists()).toBe(true)
    expect(wrapper.get('.library-layout').isVisible()).toBe(false)
    expect(wrapper.find('[data-test="enter-cover-wizard"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="add-game-root"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="batch-save-workspace"]').exists()).toBe(true)
    expect(cancel).not.toHaveBeenCalled()

    await wrapper.get('[data-test="nav-library"]').trigger('click')
    expect(wrapper.find('[data-test="root-scroll-region"]').exists()).toBe(true)
    expect(cancel).not.toHaveBeenCalled()
  })

  it('opens rule management as a third first-level page without rebootstrapping', async () => {
    const bootstrap = vi.fn(createMockBridge().bootstrap)
    const listRules = vi.fn(async () => ok({ items: [], total: 0 }))
    const prefill = vi.fn(async () => ok({
      gameId: 'unused', title: 'Unused', aliases: [], productIds: [], locations: [], engineId: null,
    }))
    const bridge = createMockBridge({ bootstrap, list_rules: listRules, get_game_save_rule_prefill: prefill })
    const wrapper = mount(App, {
      global: { plugins: [createPinia()], provide: { [bridgeKey as symbol]: bridge } },
    })
    await flushPromises()

    await wrapper.get('[data-test="nav-rules"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="nav-rules"]').attributes('aria-current')).toBe('page')
    expect(wrapper.find('[data-test="rule-management-workspace"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="cover-wizard-workspace"]').exists()).toBe(false)
    expect(listRules).toHaveBeenCalledTimes(1)
    expect(prefill).not.toHaveBeenCalled()

    await wrapper.get('[data-test="nav-library"]').trigger('click')
    await wrapper.get('[data-test="nav-rules"]').trigger('click')
    await flushPromises()
    expect(bootstrap).toHaveBeenCalledTimes(1)
    expect(listRules).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('preserves library and rule workspace state and confirms a dirty rule draft', async () => {
    const pinia = createPinia()
    const bridge = createMockBridge({
      async list_games() { return ok([fixtureGame({ title: 'Alice' })]) },
      async list_rules() {
        return ok({
          items: [{
            qualifiedId: 'builtin:kiri', ruleId: 'kiri', label: 'KiriKiri',
            ruleType: 'engine', source: 'builtin', status: 'formal', enabled: true, priority: 100,
          }],
          total: 1,
        })
      },
      async get_rule() {
        return ok({
          qualifiedId: 'builtin:kiri', ruleId: 'kiri', label: 'KiriKiri',
          ruleType: 'engine', source: 'builtin', status: 'formal', enabled: true, priority: 100,
          notes: null, references: [], sourceFile: 'engines.yaml', yamlPreview: 'id: kiri',
          draft: {
            version: '1', id: 'kiri', label: 'KiriKiri', type: 'engine', status: 'formal',
            priority: 100, enabled: true, notes: null, references: [], threshold: 1,
            all: [], any: [], negative: [],
          },
          capabilities: { edit: false, copy: true, test: true, toggle: false, delete: false, export: true },
        })
      },
    })
    const wrapper = mount(App, {
      global: { plugins: [pinia], provide: { [bridgeKey as symbol]: bridge } },
    })
    await flushPromises()
    await wrapper.get('input[aria-label="搜索游戏"]').setValue('Alice')
    const libraryScroll = wrapper.get('[data-test="library-scroll-region"]').element
    libraryScroll.scrollTop = 180

    await wrapper.get('[data-test="nav-rules"]').trigger('click')
    await flushPromises()
    await wrapper.get('.rule-list-item').trigger('click')
    await wrapper.get('[data-test="rules-tab-save"]').trigger('click')
    await flushPromises()
    const ruleStore = useRuleManagementStore(pinia)
    ruleStore.filters.query = 'custom'
    ruleStore.dirty = true
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)

    await wrapper.get('[data-test="nav-library"]').trigger('click')
    expect(wrapper.get('[data-test="nav-rules"]').attributes('aria-current')).toBe('page')
    await wrapper.get('[data-test="nav-library"]').trigger('click')
    await flushPromises()
    expect((wrapper.get('input[aria-label="搜索游戏"]').element as HTMLInputElement).value).toBe('Alice')
    expect(wrapper.get('[data-test="library-scroll-region"]').element.scrollTop).toBe(180)

    await wrapper.get('[data-test="nav-rules"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="rules-tab-save"]').attributes('aria-selected')).toBe('true')
    expect((wrapper.get('input[aria-label="搜索规则"]').element as HTMLInputElement).value).toBe('custom')
    expect(ruleStore.selectedQualifiedId).toBe('builtin:kiri')
    confirm.mockRestore()
    wrapper.unmount()
  })

  it('opens a prefilled game-specific save rule without mixing the version into its title', async () => {
    const prefill = vi.fn(async () => ok({
      gameId: 'game-1', title: '千恋＊万花', aliases: ['Senren Banka'],
      productIds: ['vndb:v19073'],
      locations: [{ kind: 'directory' as const, pathTemplate: '<winDocuments>\\Yuzusoft', category: 'save' as const, confidence: 1 }],
      engineId: 'kirikiri',
    }))
    const game = fixtureGame({ id: 'game-1', title: '千恋＊万花', version: 'v1.0' })
    const bridge = createMockBridge({
      async list_games() { return ok([game]) },
      get_game_save_rule_prefill: prefill,
    })
    const wrapper = mount(App, {
      global: { plugins: [createPinia()], provide: { [bridgeKey as symbol]: bridge } },
    })
    await flushPromises()
    await wrapper.get('[data-test="game-card-game-1"]').trigger('click')
    await wrapper.get('[data-test="create-game-save-rule"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="nav-rules"]').attributes('aria-current')).toBe('page')
    expect(wrapper.get('[data-test="rules-tab-save"]').attributes('aria-selected')).toBe('true')
    expect((wrapper.get('input[name="label"]').element as HTMLInputElement).value).toContain('千恋＊万花')
    expect((wrapper.get('input[name="label"]').element as HTMLInputElement).value).not.toContain('v1.0')
    expect(wrapper.findAll('[data-test="game-title-selectors"] input').map((input) => (input.element as HTMLInputElement).value))
      .toEqual(['千恋＊万花', 'Senren Banka'])
    expect((wrapper.get('[data-test="location-root"]').element as HTMLSelectElement).value).toBe('<winDocuments>')
    expect(prefill).toHaveBeenCalledWith({ gameId: 'game-1' })
    wrapper.unmount()
  })

  it('keeps the game drawer and dirty rule draft when a game intent is cancelled', async () => {
    const pinia = createPinia()
    const prefill = vi.fn(async () => ok({
      gameId: 'game-1', title: 'Alice', aliases: [], productIds: [], locations: [], engineId: null,
    }))
    const bridge = createMockBridge({
      async list_games() { return ok([fixtureGame({ id: 'game-1' })]) },
      get_game_save_rule_prefill: prefill,
    })
    const wrapper = mount(App, {
      global: { plugins: [pinia], provide: { [bridgeKey as symbol]: bridge } },
    })
    await flushPromises()
    const ruleStore = useRuleManagementStore(pinia)
    ruleStore.startNew('engine')
    ruleStore.dirty = true
    vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
    await wrapper.get('[data-test="game-card-game-1"]').trigger('click')
    await wrapper.get('[data-test="create-game-save-rule"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="game-detail-drawer"]').exists()).toBe(true)
    expect(ruleStore.dirty).toBe(true)
    expect(prefill).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('shows an active batch scan return entry in the game library', async () => {
    const bridge = createMockBridge({
      async current_batch_save_task() {
        return ok({
          id: 'batch-task-1', kind: 'batch_save_scan', status: 'running',
          progress: { completed: 1, total: 4 }, message: '正在扫描', result: null, error: null,
        })
      },
    })
    const wrapper = mount(App, {
      global: { plugins: [createPinia()], provide: { [bridgeKey as symbol]: bridge } },
    })
    await flushPromises()

    expect(wrapper.find('[data-test="batch-save-status-bar"]').exists()).toBe(true)
    await wrapper.get('[data-test="restore-batch-save"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="batch-save-workspace"]').exists()).toBe(true)
  })

  it('skips startup scans when quick verification is disabled', async () => {
    const startScan = vi.fn(async () => ok({ taskId: 'task-1' }))
    const bridge = createMockBridge({
      async bootstrap() {
        return ok({
          appName: 'GameSave Scout', schemaVersion: 2, portable: true, uiScale: 1,
          coverWizardSettings: {
            coverOnlineEnabled: false,
            coverVndbCandidateLimit: 5,
            coverLocalScanCandidateLimit: 10,
            coverOptimizeEnabled: true,
            coverLocalScanDepth: 2,
          },
          libraryScanSettings: { startupQuickScan: false, scanConcurrency: 1 },
          batchSaveSettings: { customRoots: [] },
        })
      },
      async list_roots() { return ok([fixtureRoot()]) },
      start_scan: startScan,
    })
    mount(App, {
      global: { plugins: [createPinia()], provide: { [bridgeKey as symbol]: bridge } },
    })

    await flushPromises()

    expect(startScan).not.toHaveBeenCalled()
  })

  it('starts quick verification only for enabled roots', async () => {
    const startScan = vi.fn(async () => ok({ taskId: 'task-1' }))
    const bridge = createMockBridge({
      async list_roots() {
        return ok([fixtureRoot({ id: 'enabled' }), fixtureRoot({ id: 'disabled', enabled: false })])
      },
      start_scan: startScan,
    })
    mount(App, {
      global: { plugins: [createPinia()], provide: { [bridgeKey as symbol]: bridge } },
    })

    await flushPromises()

    expect(startScan).toHaveBeenCalledTimes(1)
    expect(startScan).toHaveBeenCalledWith({ rootId: 'enabled', kind: 'quick' })
  })

  it('starts one full scan after a new root is saved', async () => {
    const root = fixtureRoot({ id: 'new-root' })
    const startScan = vi.fn(async () => ok({ taskId: 'task-full' }))
    const bridge = createMockBridge({
      async list_roots() { return ok([]) },
      async add_root() { return ok(root) },
      start_scan: startScan,
    })
    const wrapper = mount(App, {
      global: { plugins: [createPinia()], provide: { [bridgeKey as symbol]: bridge } },
    })
    await flushPromises()
    await wrapper.get('[data-test="add-game-root"]').trigger('click')
    await wrapper.get('[data-test="display-path"]').setValue('D:\\Games')
    await wrapper.get('.dialog-card form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('.dialog-card').exists()).toBe(false)
    expect(startScan).toHaveBeenCalledWith({ rootId: root.id, kind: 'full' })
  })

  it('does not automatically scan after an existing root is edited', async () => {
    const root = fixtureRoot()
    const startScan = vi.fn(async () => ok({ taskId: 'unexpected' }))
    const bridge = createMockBridge({
      async bootstrap() {
        return ok({
          appName: 'GameSave Scout', schemaVersion: 2, portable: true, uiScale: 1,
          coverWizardSettings: {
            coverOnlineEnabled: false,
            coverVndbCandidateLimit: 5,
            coverLocalScanCandidateLimit: 10,
            coverOptimizeEnabled: true,
            coverLocalScanDepth: 2,
          },
          libraryScanSettings: { startupQuickScan: false, scanConcurrency: 1 },
          batchSaveSettings: { customRoots: [] },
        })
      },
      async list_roots() { return ok([root]) },
      async update_root() { return ok(root) },
      start_scan: startScan,
    })
    const wrapper = mount(App, {
      global: { plugins: [createPinia()], provide: { [bridgeKey as symbol]: bridge } },
    })
    await flushPromises()
    await wrapper.get('[data-test="edit-root"]').trigger('click')
    await wrapper.get('.dialog-card form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('.dialog-card').exists()).toBe(false)
    expect(startScan).not.toHaveBeenCalled()
  })

  it('keeps batch selection and group management as independent actions in one visual group', async () => {
    const bridge = createMockBridge({
      async list_games() { return ok([fixtureGame()]) },
    })
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia()],
        provide: { [bridgeKey as symbol]: bridge },
      },
    })
    await flushPromises()

    const actions = wrapper.get('[aria-label="游戏管理"]')
    expect(actions.findAll('button').map((item) => item.text())).toEqual(['批量选择', '管理分组'])
    expect(wrapper.get('[data-test="nav-covers"]').text()).toBe('批量封面')
    expect(wrapper.find('[data-test="enter-cover-wizard"]').exists()).toBe(false)
    expect(wrapper.get('.library-toolbar').find('[data-test="manage-groups"]').exists()).toBe(false)

    await actions.get('[data-test="enter-batch-mode"]').trigger('click')
    expect(actions.get('[data-test="enter-batch-mode"]').text()).toBe('退出批量选择')
  })

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

  it('uses a compact two-row toolbar before 120% scale can hide its last control', () => {
    const stackRule = Array.from(document.styleSheets)
      .flatMap((sheet) => Array.from(sheet.cssRules))
      .find((rule) => rule.cssText.startsWith('@container (max-width: 44rem)'))

    expect(stackRule).toBeDefined()
    if (!stackRule) return
    expect(stackRule.cssText).toContain('.library-toolbar')
    expect(stackRule.cssText).toContain('grid-template-columns: repeat(3, minmax(0, 1fr))')
    expect(stackRule.cssText).toContain('.library-toolbar input[type="search"]')
    expect(stackRule.cssText).toContain('grid-column: span 2')
  })

  it('keeps the full brand aligned with a fixed-width library sidebar', async () => {
    const wrapper = mount(App, {
      global: { plugins: [createPinia()], provide: { [bridgeKey as symbol]: createMockBridge() } },
    })
    await flushPromises()

    expect(wrapper.get('.app-brand-full').text()).toContain('GameSave Scout')
    expect(wrapper.find('.app-brand-compact').exists()).toBe(false)

    const headerStyle = getComputedStyle(wrapper.get('.app-global-header').element)
    const libraryStyle = getComputedStyle(wrapper.get('.library-layout').element)
    expect(headerStyle.gridTemplateColumns).toBe('15.625rem minmax(0, 1fr) auto')
    expect(libraryStyle.gridTemplateColumns).toBe('15.625rem minmax(0, 1fr)')

    const compactRule = Array.from(document.styleSheets)
      .flatMap((sheet) => Array.from(sheet.cssRules))
      .find((rule) => rule.cssText.startsWith('@media (max-width: 68rem)'))
    expect(compactRule).toBeDefined()
    expect(compactRule?.cssText).not.toContain('.app-brand-full')
    expect(compactRule?.cssText).not.toContain('grid-template-columns: 11rem')
    wrapper.unmount()
  })

  it('keeps all navigation entries as compact content-width tabs', async () => {
    const wrapper = mount(App, {
      global: { plugins: [createPinia()], provide: { [bridgeKey as symbol]: createMockBridge() } },
    })
    await flushPromises()

    expect(wrapper.findAll('.primary-navigation button')).toHaveLength(4)
    expect(wrapper.find('.primary-navigation select').exists()).toBe(false)
    expect(getComputedStyle(wrapper.get('.primary-navigation').element).display).toBe('flex')
    expect(getComputedStyle(wrapper.get('.primary-navigation button').element).flexGrow).toBe('0')
    expect(wrapper.get('.ui-scale-label').text()).toBe('界面缩放')
    expect(wrapper.get('.add-root-full').text()).toContain('添加游戏目录')
    expect(wrapper.get('.add-root-compact').text()).toContain('目录')

    const compactRule = Array.from(document.styleSheets)
      .flatMap((sheet) => Array.from(sheet.cssRules))
      .find((rule) => rule.cssText.startsWith('@media (max-width: 68rem)'))
    expect(compactRule).toBeDefined()
    expect(compactRule?.cssText).toContain('.ui-scale-label')
    expect(compactRule?.cssText).toContain('.add-root-full')
    wrapper.unmount()
  })

  it('keeps library controls outside the independently scrollable game content', async () => {
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

    const controls = wrapper.get('[data-test="library-fixed-controls"]')
    const scrollRegion = wrapper.get('[data-test="library-scroll-region"]')
    expect(controls.find('.content-heading').exists()).toBe(true)
    expect(controls.find('.library-toolbar').exists()).toBe(true)
    expect(scrollRegion.find('[data-test="game-grid"]').exists()).toBe(true)
    expect(getComputedStyle(scrollRegion.element).overflowY).toBe('auto')
    expect(getComputedStyle(wrapper.get('.app-shell').element).overflow).toBe('hidden')
    wrapper.unmount()
  })

  it('opens covers as a first-level workspace and closes its session before restoring library state', async () => {
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
    const closeCoverWizard = vi.fn(async () => ok({ closed: true }))
    const bridge = createMockBridge({
      async list_games() { return ok([fixtureGame()]) },
      async start_cover_wizard() {
        return ok({
          id: 'wizard-1',
          queue: [{
            gameId: 'game-1', title: 'Alice', version: null, initialHasCover: false,
            status: 'pending', candidateCount: 0, error: null,
          }],
          currentGameId: 'game-1', includeExisting: false, sourceOperationActive: false,
        })
      },
      close_cover_wizard: closeCoverWizard,
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
    const gameScroll = wrapper.get('[data-test="library-scroll-region"]').element
    const rootScroll = wrapper.get('[data-test="root-scroll-region"]').element
    gameScroll.scrollTop = 240
    rootScroll.scrollTop = 120

    await wrapper.get('[data-test="nav-covers"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="nav-covers"]').attributes('aria-current')).toBe('page')
    expect(wrapper.get('[data-test="cover-wizard-workspace"]').attributes('role')).toBeUndefined()
    expect(wrapper.get('[data-test="cover-wizard-workspace"]').attributes('aria-modal')).toBeUndefined()
    expect(wrapper.get('[data-test="cover-wizard-workspace"]').text()).not.toContain('返回游戏库')
    expect(document.body.contains(layout)).toBe(true)
    expect(wrapper.get('.library-layout').isVisible()).toBe(false)

    await wrapper.get('[data-test="nav-library"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="cover-wizard-workspace"]').exists()).toBe(false)
    expect(closeCoverWizard).toHaveBeenCalledWith({ sessionId: 'wizard-1' })
    expect((wrapper.get('input[aria-label="搜索游戏"]').element as HTMLInputElement).value).toBe('Alice')
    expect(wrapper.get('[data-test="library-scroll-region"]').element).toBe(gameScroll)
    expect(wrapper.get('[data-test="root-scroll-region"]').element).toBe(rootScroll)
    expect(wrapper.get('[data-test="library-scroll-region"]').element.scrollTop).toBe(240)
    expect(wrapper.get('[data-test="root-scroll-region"]').element.scrollTop).toBe(120)
    expect(scrollTo).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('returns the game content to the top when filters change', async () => {
    const bridge = createMockBridge({
      async list_games() { return ok([fixtureGame()]) },
    })
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia()],
        provide: { [bridgeKey as symbol]: bridge },
      },
    })
    await flushPromises()
    const scrollRegion = wrapper.get('[data-test="library-scroll-region"]').element
    scrollRegion.scrollTop = 240

    await wrapper.get('input[aria-label="搜索游戏"]').setValue('Alice')
    await flushPromises()

    expect(scrollRegion.scrollTop).toBe(0)
    wrapper.unmount()
  })

  it('wires the group filter and restores focus after closing group management', async () => {
    const bridge = createMockBridge({
      async list_games() {
        return ok([
          fixtureGame({ id: 'grouped', title: 'Grouped', groupIds: ['group-rpg'] }),
          fixtureGame({ id: 'plain', title: 'Plain', groupIds: [] }),
        ])
      },
      async list_game_groups() {
        return ok([{
          id: 'group-rpg', name: 'RPG', gameCount: 1,
          createdAt: 'now', updatedAt: 'now',
        }])
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

    await wrapper.get('select[aria-label="分组筛选"]').setValue('ungrouped')
    await flushPromises()
    expect(wrapper.text()).toContain('Plain')
    expect(wrapper.text()).not.toContain('Grouped')

    const entry = wrapper.get('[data-test="manage-groups"]')
    await entry.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="group-management-dialog"]').exists()).toBe(true)
    expect(wrapper.get('.library-layout').attributes('inert')).toBeDefined()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(wrapper.find('[data-test="group-management-dialog"]').exists()).toBe(false)
    expect(document.activeElement).toBe(entry.element)
    wrapper.unmount()
  })

  it('opens group management from the detail drawer and restores that button focus', async () => {
    const bridge = createMockBridge({
      async list_games() { return ok([fixtureGame()]) },
      async list_game_groups() { return ok([]) },
    })
    const wrapper = mount(App, {
      attachTo: document.body,
      global: {
        plugins: [createPinia()],
        provide: { [bridgeKey as symbol]: bridge },
      },
    })
    await flushPromises()
    await wrapper.get('[data-test="game-card-game-1"]').trigger('click')
    await flushPromises()
    const entry = wrapper.get('[data-test="manage-groups-from-detail"]')

    await entry.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="group-management-dialog"]').exists()).toBe(true)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()

    expect(wrapper.find('[data-test="group-management-dialog"]').exists()).toBe(false)
    expect(document.activeElement).toBe(entry.element)
    wrapper.unmount()
  })

  it('connects before rendering the empty-library message', async () => {
    const wrapper = mount(App, { global: { plugins: [createPinia()] } })
    expect(wrapper.get('h1').text()).toBe('GameSave Scout')
    expect(wrapper.text()).toContain('正在连接本地数据库…')

    await flushPromises()

    expect(wrapper.text()).toContain('还没有添加游戏目录')
  })

  it('restores UI scale from bootstrap and persists changes through the bridge', async () => {
    localStorage.setItem('gamesave-scout.ui-scale', '0.9')
    const setUiScale = vi.fn(async (input: { uiScale: UiScaleValue }) => ok({ uiScale: input.uiScale }))
    const bridge = createMockBridge({
      async bootstrap() {
        return ok({
          appName: 'GameSave Scout', schemaVersion: 1, portable: true, uiScale: 1.2,
          libraryScanSettings: { startupQuickScan: true, scanConcurrency: 1 },
          coverWizardSettings: {
            coverOnlineEnabled: false,
            coverVndbCandidateLimit: 5,
            coverLocalScanCandidateLimit: 10,
            coverOptimizeEnabled: true,
            coverLocalScanDepth: 2,
          },
          batchSaveSettings: { customRoots: [] },
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
    expect(localStorage.getItem('gamesave-scout.ui-scale')).toBe('0.9')
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

  it('keeps one batch-mode toggle in the fixed heading', async () => {
    const bridge = createMockBridge({
      async list_games() { return ok([fixtureGame({ id: 'game-1' })]) },
    })
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia()],
        provide: { [bridgeKey as symbol]: bridge },
      },
    })
    await flushPromises()

    const toggle = wrapper.get('[data-test="enter-batch-mode"]')
    expect(toggle.text()).toBe('批量选择')
    expect(toggle.attributes('aria-pressed')).toBe('false')

    await toggle.trigger('click')

    const exitToggle = wrapper.get('[data-test="enter-batch-mode"]')
    expect(exitToggle.text()).toBe('退出批量选择')
    expect(exitToggle.attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-test="batch-management-bar"]').text()).not.toContain('退出批量选择')

    await exitToggle.trigger('click')

    expect(wrapper.get('[data-test="enter-batch-mode"]').text()).toBe('批量选择')
    expect(wrapper.find('[data-test="batch-management-bar"]').exists()).toBe(false)
  })

  it('keeps the batch group modal above sticky batch controls', async () => {
    const bridge = createMockBridge({
      async list_games() { return ok([fixtureGame({ id: 'game-1' })]) },
      async list_game_groups() { return ok([fixtureGroup({ id: 'group-rpg' })]) },
    })
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia()],
        provide: { [bridgeKey as symbol]: bridge },
      },
    })
    await flushPromises()

    await wrapper.get('[data-test="enter-batch-mode"]').trigger('click')
    await wrapper.get('[data-test="game-card-game-1"]').trigger('click')
    const batchBar = wrapper.get('[data-test="batch-management-bar"]')
    await wrapper.get('[data-test="batch-group"]').trigger('click')

    const dialog = wrapper.get('[data-test="batch-group-dialog"]')
    const backdrop = dialog.element.parentElement as HTMLElement
    const backdropZIndex = Number.parseInt(getComputedStyle(backdrop).zIndex, 10)
    const batchBarZIndex = Number.parseInt(getComputedStyle(batchBar.element).zIndex, 10)

    expect(backdropZIndex).toBeGreaterThan(batchBarZIndex)
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
      async (_input: Parameters<GameSaveScoutBridge['remove_games']>[0]) => ok({
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
    expect(wrapper.get('[data-test="game-card-save-1"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-test="batch-counts"]').text()).toContain('已选择 2 个')
    expect(wrapper.get('[data-test="batch-counts"]').text()).toContain('已安装 1')
    expect(wrapper.get('[data-test="batch-counts"]').text()).toContain('仅存档 1')
    expect(wrapper.get('[data-test="batch-delete"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="batch-group"]').attributes('disabled')).toBeUndefined()

    await wrapper.get('[data-test="game-card-save-1"]').trigger('click')

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

  it('keeps batch mode and remaining selections after a group update', async () => {
    const initialGames = [
      fixtureGame({ id: 'installed-1', status: 'installed' }),
      fixtureGame({ id: 'save-1', status: 'save_only' }),
    ]
    let listCalls = 0
    const update = vi.fn(async () => ok({ addedCount: 1, removedCount: 0, unchangedCount: 1 }))
    const bridge = createMockBridge({
      async list_games() {
        listCalls += 1
        return ok(listCalls === 1 ? initialGames : [initialGames[1]])
      },
      async list_game_groups() { return ok([fixtureGroup({ id: 'group-rpg', name: 'RPG' })]) },
      update_game_group_memberships: update,
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
    await wrapper.get('[data-test="game-card-save-1"]').trigger('click')
    await wrapper.get('[data-test="batch-group"]').trigger('click')
    await wrapper.get('[data-test="batch-group-select"]').setValue('group-rpg')
    await wrapper.get('[data-test="batch-group-form"]').trigger('submit')
    await flushPromises()

    expect(update).toHaveBeenCalledWith({
      groupId: 'group-rpg',
      gameIds: ['installed-1', 'save-1'],
      mode: 'add',
    })
    expect(wrapper.find('[data-test="batch-group-dialog"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="batch-management-bar"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="batch-counts"]').text()).toContain('已选择 1 个')
    expect(wrapper.get('[data-test="batch-counts"]').text()).toContain('仅存档 1')
    expect(wrapper.get('[data-test="game-card-save-1"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-test="batch-result"]').text()).toContain('已加入 1，已移出 0，未变化 1')
  })

  it('keeps the batch group dialog and selection after an update failure', async () => {
    const bridge = createMockBridge({
      async list_games() { return ok([fixtureGame({ id: 'save-1', status: 'save_only' })]) },
      async list_game_groups() { return ok([fixtureGroup({ id: 'group-rpg' })]) },
      async update_game_group_memberships() {
        return { ok: false, error: { code: 'failed', message: '批量调整失败' } }
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
    await wrapper.get('[data-test="game-card-save-1"]').trigger('click')
    await wrapper.get('[data-test="batch-group"]').trigger('click')
    await wrapper.get('[data-test="batch-group-select"]').setValue('group-rpg')
    await wrapper.get('[data-test="batch-group-mode-remove"]').setValue(true)
    await wrapper.get('[data-test="batch-group-form"]').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[data-test="batch-group-dialog"]').exists()).toBe(true)
    expect(wrapper.get('[role="alert"]').text()).toContain('批量调整失败')
    expect((wrapper.get('[data-test="batch-group-select"]').element as HTMLSelectElement).value).toBe('group-rpg')
    expect((wrapper.get('[data-test="batch-group-mode-remove"]').element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.get('[data-test="game-card-save-1"]').attributes('aria-pressed')).toBe('true')
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
