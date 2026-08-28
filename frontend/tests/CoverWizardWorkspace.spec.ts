import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CoverWizardWorkspace from '../src/features/covers/CoverWizardWorkspace.vue'
import type { CoverCandidate, CoverWizardSettings } from '../src/api/contracts'
import { createMockBridge, fixtureCoverWizard, fixtureGame, ok } from '../src/api/mockBridge'
import '../src/features/library/library.css'
import { useCoverWizardStore } from '../src/features/covers/coverWizardStore'

const settings: CoverWizardSettings = {
  coverOnlineEnabled: false,
  coverVndbCandidateLimit: 5,
  coverLocalScanCandidateLimit: 10,
  coverOptimizeEnabled: true,
  coverLocalScanDepth: 2,
}

beforeEach(() => vi.restoreAllMocks())
afterEach(() => document.documentElement.classList.remove('cover-wizard-open'))

describe('CoverWizardWorkspace', () => {
  it('places launch before candidate settings in one heading action group', async () => {
    const wrapper = mount(CoverWizardWorkspace, {
      props: {
        bridge: createMockBridge({ async start_cover_wizard() { return ok(snapshot()) } }),
        games: [fixtureGame({ id: 'game-1', mainExeRelpath: 'Alice.exe' })],
        settings,
      },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()

    const actions = wrapper.get('[data-test="cover-heading-actions"]')
    const controls = actions.findAll('button')
    expect(controls.map((control) => control.text())).toEqual(['启动游戏', '候选设置'])
    expect(getComputedStyle(actions.element).display).toBe('grid')
    expect(getComputedStyle(actions.element).gridTemplateColumns).toContain('max-content')
    expect(getComputedStyle(actions.element).gridTemplateColumns).toContain('minmax(0, 24rem)')
    expect(actions.get('[data-test="cover-launch-current"]').element.nextElementSibling).toBe(
      actions.get('.cover-wizard-settings').element,
    )
    expect(getComputedStyle(actions.get('[data-test="cover-launch-current"]').element).minHeight).toBe(
      getComputedStyle(actions.get('[data-test="cover-settings-trigger"]').element).minHeight,
    )
    expect(wrapper.get('.cover-review-title-row').find('[data-test="cover-launch-current"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it.each([
    ['installed without a main program', fixtureGame({ id: 'game-1', mainExeRelpath: null })],
    ['missing', fixtureGame({ id: 'game-1', status: 'missing', mainExeRelpath: 'Alice.exe' })],
    ['save-only', fixtureGame({ id: 'game-1', status: 'save_only', mainExeRelpath: 'Alice.exe' })],
  ])('disables batch cover launch for %s games', async (_label, game) => {
    const wrapper = mount(CoverWizardWorkspace, {
      props: {
        bridge: createMockBridge({ async start_cover_wizard() { return ok(snapshot()) } }),
        games: [game],
        settings,
      },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()

    expect(wrapper.get('[data-test="cover-launch-current"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('launches the current game once without changing cover workspace state', async () => {
    const pinia = createPinia()
    const launchResult = ok({
      gameId: 'game-1',
      pid: 1234,
      launchedAt: '2026-08-28T16:00:00+08:00',
    })
    let finishLaunch = () => {}
    const launch = vi.fn(() => new Promise<typeof launchResult>((resolve) => {
      finishLaunch = () => resolve(launchResult)
    }))
    const bridge = createMockBridge({
      async start_cover_wizard() { return ok(snapshot()) },
      async list_cover_candidates() { return ok([candidate()]) },
      launch_game: launch,
    })
    const wrapper = mount(CoverWizardWorkspace, {
      props: {
        bridge,
        games: [fixtureGame({ id: 'game-1', mainExeRelpath: 'Alice.exe' })],
        settings,
      },
      global: { plugins: [pinia] },
    })
    await flushPromises()
    const store = useCoverWizardStore(pinia)
    store.selectedCandidateId = 'candidate-1'
    const gallery = wrapper.get('[data-test="cover-gallery-scroll"]').element
    gallery.scrollTop = 123
    const stateBefore = {
      gameId: store.selectedGameId,
      candidateId: store.selectedCandidateId,
      candidates: [...store.candidates],
    }

    const button = wrapper.get('[data-test="cover-launch-current"]')
    await button.trigger('click')
    expect(button.attributes('disabled')).toBeDefined()
    await button.trigger('click')
    expect(launch).toHaveBeenCalledTimes(1)
    finishLaunch()
    await flushPromises()

    expect(launch).toHaveBeenCalledWith({ gameId: 'game-1' })
    expect(wrapper.get('[data-test="cover-launch-message"]').text()).toBe('游戏已启动')
    expect(button.attributes('disabled')).toBeUndefined()
    expect({
      gameId: store.selectedGameId,
      candidateId: store.selectedCandidateId,
      candidates: [...store.candidates],
    }).toEqual(stateBefore)
    expect(gallery.scrollTop).toBe(123)
    wrapper.unmount()
  })

  it.each([
    ['business failure', async () => ({
      ok: false as const,
      error: { code: 'launch_failed', message: '工作目录不存在' },
    }), '工作目录不存在'],
    ['rejected promise', async () => { throw new Error('bridge unavailable') }, '启动游戏失败，请稍后重试。'],
  ])('recovers the batch launch button after %s', async (_label, launchGame, expected) => {
    const wrapper = mount(CoverWizardWorkspace, {
      props: {
        bridge: createMockBridge({
          async start_cover_wizard() { return ok(snapshot()) },
          launch_game: launchGame,
        }),
        games: [fixtureGame({ id: 'game-1', mainExeRelpath: 'Alice.exe' })],
        settings,
      },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()

    const button = wrapper.get('[data-test="cover-launch-current"]')
    await button.trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="cover-launch-message"]').text()).toBe(expected)
    expect(button.attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('keeps fixed controls outside isolated queue and gallery scroll regions', async () => {
    const wrapper = mount(CoverWizardWorkspace, {
      props: {
        bridge: createMockBridge({ async start_cover_wizard() { return ok(snapshot()) } }),
        games: [fixtureGame()],
        settings,
      },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()

    const workspace = wrapper.get('[data-test="cover-wizard-workspace"]')
    const queue = wrapper.get('[data-test="cover-queue-scroll"]')
    const gallery = wrapper.get('[data-test="cover-gallery-scroll"]')
    expect(getComputedStyle(workspace.element).overflowY).toBe('hidden')
    expect(getComputedStyle(queue.element).overflowY).toBe('auto')
    expect(getComputedStyle(gallery.element).overflowY).toBe('auto')
    expect(wrapper.get('.cover-review-actions').element.parentElement).toBe(
      wrapper.get('.cover-wizard-review').element,
    )
    expect(document.documentElement.classList.contains('cover-wizard-open')).toBe(false)
    wrapper.unmount()
    expect(document.documentElement.classList.contains('cover-wizard-open')).toBe(false)
  })

  it('returns the candidate gallery to the top after selecting another game', async () => {
    const wizard = fixtureCoverWizard({
      id: 'wizard-1',
      currentGameId: 'game-1',
      queue: [
        { gameId: 'game-1', title: 'Alice', version: null, initialHasCover: false, status: 'ready', candidateCount: 1, error: null },
        { gameId: 'game-2', title: 'Bob', version: null, initialHasCover: false, status: 'pending', candidateCount: 0, error: null },
      ],
    })
    const bridge = createMockBridge({
      async start_cover_wizard() { return ok(wizard) },
      async list_cover_candidates() { return ok([]) },
    })
    const wrapper = mount(CoverWizardWorkspace, {
      props: {
        bridge,
        games: [
          fixtureGame({ id: 'game-1', title: 'Alice' }),
          fixtureGame({ id: 'game-2', title: 'Bob' }),
        ],
        settings,
      },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()
    const gallery = wrapper.get('[data-test="cover-gallery-scroll"]').element
    gallery.scrollTop = 200

    await wrapper.findAll('.cover-queue-item')[1].trigger('click')
    await flushPromises()

    expect(wrapper.get('.cover-review-heading h2').text()).toBe('Bob')
    expect(gallery.scrollTop).toBe(0)
    wrapper.unmount()
  })

  it('renders queue and candidate gallery with accessible selection and actions', async () => {
    const game = fixtureGame({ id: 'game-1', title: 'Alice' })
    const cover = candidate()
    const adopt = vi.fn(async () => ok({
      game: fixtureGame({ id: 'game-1', coverRevision: 1 }),
      snapshot: fixtureCoverWizard({ id: 'wizard-1', currentGameId: null }),
    }))
    const bridge = createMockBridge({
      async start_cover_wizard() { return ok(snapshot()) },
      async list_cover_candidates() { return ok([cover]) },
      adopt_cover_candidate: adopt,
    })
    const wrapper = mount(CoverWizardWorkspace, {
      props: { bridge, games: [game], settings },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()

    expect(wrapper.get('[role="radio"]').attributes('aria-checked')).toBe('false')
    expect(wrapper.get('img').attributes('alt')).toBe('Alice · VNDB候选')
    const adoptButton = wrapper.findAll('button').find((button) => button.text() === '采用并下一个')!
    expect(adoptButton.attributes('disabled')).toBeDefined()
    await wrapper.get('[role="radio"]').trigger('click')
    expect(wrapper.get('[role="radio"]').attributes('aria-checked')).toBe('true')
    await adoptButton.trigger('click')
    await flushPromises()

    expect(adopt).toHaveBeenCalledWith({ sessionId: 'wizard-1', candidateId: 'candidate-1' })
    expect(wrapper.emitted('updated')).toHaveLength(1)
    wrapper.unmount()
  })

  it('shows the current game version as a separate local-only badge', async () => {
    const game = fixtureGame({ id: 'game-1', title: 'Alice', version: 'v1.0.8' })
    const wrapper = mount(CoverWizardWorkspace, {
      props: {
        bridge: createMockBridge({
          async start_cover_wizard() {
            return ok(fixtureCoverWizard({
              id: 'wizard-1',
              currentGameId: game.id,
              queue: [{
                gameId: game.id,
                title: game.title,
                version: game.version,
                initialHasCover: false,
                status: 'pending',
                candidateCount: 0,
                error: null,
              }],
            }))
          },
        }),
        games: [game],
        settings,
      },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()

    expect(wrapper.get('.cover-review-heading h2').text()).toBe('Alice')
    expect(wrapper.get('.cover-review-version').text()).toBe('v1.0.8')
    wrapper.unmount()
  })

  it('disables online and unavailable local sources and shows privacy text', async () => {
    const saveOnly = fixtureGame({ id: 'game-1', status: 'save_only', installPath: null })
    const wrapper = mount(CoverWizardWorkspace, {
      props: {
        bridge: createMockBridge({ async start_cover_wizard() { return ok(snapshot()) } }),
        games: [saveOnly],
        settings,
      },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()

    const buttons = wrapper.findAll('.cover-source-actions button')
    expect(buttons[0].attributes('disabled')).toBeDefined()
    expect(buttons[1].attributes('disabled')).toBeDefined()
    expect(buttons[2].attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('只发送游戏标题，不发送版本号、安装路径或本地文件')
    wrapper.unmount()
  })

  it('confirms batch VNDB and does not start directory import after cancel', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const vndb = vi.fn(async () => ok({ taskId: 'task-1' }))
    const directory = vi.fn(async () => ok({ taskId: 'task-2' }))
    const bridge = createMockBridge({
      async start_cover_wizard() { return ok(snapshot()) },
      async choose_directory() { return ok(null) },
      start_cover_vndb_search: vndb,
      start_cover_directory_import: directory,
    })
    const wrapper = mount(CoverWizardWorkspace, {
      props: {
        bridge,
        games: [fixtureGame()],
        settings: { ...settings, coverOnlineEnabled: true },
      },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()
    const buttons = wrapper.findAll('.cover-source-actions button')

    await buttons[1].trigger('click')
    await flushPromises()
    expect(window.confirm).toHaveBeenCalledWith('将向 VNDB 发送 1 个游戏标题，是否继续？')
    expect(vndb).toHaveBeenCalled()
    await buttons[3].trigger('click')
    await flushPromises()
    expect(directory).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps settings form and reports a save failure', async () => {
    const bridge = createMockBridge({
      async start_cover_wizard() { return ok(snapshot()) },
      async set_cover_wizard_settings() {
        return { ok: false, error: { code: 'config_save_failed', message: '磁盘只读' } }
      },
    })
    const wrapper = mount(CoverWizardWorkspace, {
      props: { bridge, games: [fixtureGame()], settings },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()
    await wrapper.get('[data-test="cover-settings-trigger"]').trigger('click')
    const online = wrapper.get('.cover-wizard-settings input[type="checkbox"]')
    await online.setValue(true)
    const optimize = wrapper.get('[data-test="cover-optimize-mode"]')
    const depth = wrapper.get('[data-test="cover-local-scan-depth"]')
    await optimize.setValue('preserve')
    await depth.setValue('3')
    await wrapper.get('.cover-wizard-settings form').trigger('submit')
    await flushPromises()

    expect((online.element as HTMLInputElement).checked).toBe(true)
    expect((optimize.element as HTMLSelectElement).value).toBe('preserve')
    expect((depth.element as HTMLSelectElement).value).toBe('3')
    expect(wrapper.text()).toContain('设置未保存：磁盘只读')
    wrapper.unmount()
  })

  it('emits the complete saved settings and sends the selected shallow depth', async () => {
    const save = vi.fn(async (input: CoverWizardSettings) => ok(input))
    const shallow = vi.fn(async () => ok({ taskId: 'task-depth' }))
    const wrapper = mount(CoverWizardWorkspace, {
      props: {
        bridge: createMockBridge({
          async start_cover_wizard() { return ok(snapshot()) },
          set_cover_wizard_settings: save,
          start_cover_shallow_scan: shallow,
        }),
        games: [fixtureGame({ id: 'game-1', installPath: 'D:\\Games\\Alice' })],
        settings,
      },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()
    await wrapper.get('[data-test="cover-settings-trigger"]').trigger('click')
    await wrapper.get('[data-test="cover-optimize-mode"]').setValue('preserve')
    await wrapper.get('[data-test="cover-local-scan-depth"]').setValue('3')
    await wrapper.get('.cover-wizard-settings form').trigger('submit')
    await flushPromises()

    const expected = { ...settings, coverOptimizeEnabled: false, coverLocalScanDepth: 3 as const }
    expect(save).toHaveBeenCalledWith(expected)
    expect(wrapper.emitted('settingsUpdated')).toEqual([[expected]])

    const shallowButton = wrapper.findAll('.cover-source-actions button')
      .find((button) => button.text() === '浅层扫描')!
    await shallowButton.trigger('click')
    await flushPromises()
    expect(shallow).toHaveBeenCalledWith({
      sessionId: 'wizard-1', gameId: 'game-1', limit: 10, depth: 3,
    })
    wrapper.unmount()
  })

  it('closes settings with Escape without treating the first-level workspace as a dialog', async () => {
    const wrapper = mount(CoverWizardWorkspace, {
      attachTo: document.body,
      props: {
        bridge: createMockBridge({ async start_cover_wizard() { return ok(snapshot()) } }),
        games: [fixtureGame()],
        settings,
      },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()
    await wrapper.get('[data-test="cover-settings-trigger"]').trigger('click')
    await wrapper.get('.cover-wizard-settings form').trigger('keydown', { key: 'Escape' })
    await flushPromises()

    expect(wrapper.find('[data-test="cover-settings-popover"]').exists()).toBe(false)
    expect(wrapper.emitted('close')).toBeUndefined()
    expect(wrapper.get('[data-test="cover-wizard-workspace"]').attributes('role')).toBeUndefined()
    expect(wrapper.get('[data-test="cover-wizard-workspace"]').attributes('aria-modal')).toBeUndefined()
    expect(wrapper.text()).not.toContain('返回游戏库')

    await wrapper.get('[data-test="cover-wizard-workspace"]').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(wrapper.emitted('close')).toBeUndefined()
    wrapper.unmount()
  })
})

function snapshot() {
  return fixtureCoverWizard({
    id: 'wizard-1',
    currentGameId: 'game-1',
    queue: [{
      gameId: 'game-1', title: 'Alice', initialHasCover: false,
      version: null,
      status: 'ready', candidateCount: 1, error: null,
    }],
  })
}

function candidate(): CoverCandidate {
  return {
    id: 'candidate-1', gameId: 'game-1', source: 'vndb', sourceLabel: 'VNDB',
    displayName: 'Alice', width: 600, height: 900, matchKind: 'exact', score: 100,
    evidence: ['标题精确匹配'], previewUrl: '/candidate.webp', vndbId: 'v1',
  }
}
