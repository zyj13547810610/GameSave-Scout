import { enableAutoUnmount, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GameShelfBridge } from '../src/api/contracts'
import { createMockBridge, fixtureGame, ok } from '../src/api/mockBridge'
import GameDetailDrawer from '../src/features/library/GameDetailDrawer.vue'
import '../src/features/library/library.css'

enableAutoUnmount(afterEach)

afterEach(() => {
  document.documentElement.classList.remove('detail-open')
  document.body.style.paddingRight = ''
  document.body.innerHTML = ''
})

describe('GameDetailDrawer', () => {
  it('uses the full original cover', () => {
    const wrapper = mount(GameDetailDrawer, {
      props: {
        game: fixtureGame({ coverOriginalUrl: '/cover/original' }),
        bridge: createMockBridge(),
      },
      attachTo: document.body,
    })

    expect(wrapper.get('[data-test="detail-cover"]').attributes('src')).toBe('/cover/original')
  })

  it('keeps every cover aspect ratio inside the bounded overview frame', () => {
    const wrapper = mount(GameDetailDrawer, {
      props: {
        game: fixtureGame({ coverOriginalUrl: '/cover/portrait' }),
        bridge: createMockBridge(),
      },
      attachTo: document.body,
    })

    const frameStyle = getComputedStyle(wrapper.get('.detail-cover-frame').element)
    const imageStyle = getComputedStyle(wrapper.get('[data-test="detail-cover"]').element)

    expect(frameStyle.overflow).toBe('hidden')
    expect(imageStyle.width).toBe('auto')
    expect(imageStyle.height).toBe('auto')
    expect(imageStyle.maxWidth).toBe('100%')
    expect(imageStyle.maxHeight).toBe('100%')
    expect(frameStyle.maxHeight).toBe('22.5rem')
  })

  it('orders detail sections for common tasks and restores their default state', () => {
    const wrapper = mount(GameDetailDrawer, {
      props: {
        game: fixtureGame({ mainExeRelpath: 'Alice.exe' }),
        bridge: createMockBridge(),
      },
    })
    const selectors = [
      '[data-test="detail-overview"]',
      '[data-test="detail-cover-actions"]',
      '[data-test="game-settings-section"]',
      '[data-test="save-locations-section"]',
      '[data-test="game-groups-section"]',
      '[data-test="engine-section"]',
      '[data-test="record-section"]',
    ]
    const elements = selectors.map((selector) => wrapper.get(selector).element)

    for (let index = 0; index < elements.length - 1; index += 1) {
      expect(elements[index].compareDocumentPosition(elements[index + 1]))
        .toBe(Node.DOCUMENT_POSITION_FOLLOWING)
    }
    expect(wrapper.get('[data-test="game-settings-section"]').attributes()).toHaveProperty('open')
    expect(wrapper.get('[data-test="save-locations-section"]').attributes()).toHaveProperty('open')
    expect(wrapper.get('[data-test="game-groups-section"]').attributes()).not.toHaveProperty('open')
    expect(wrapper.get('[data-test="engine-section"]').attributes()).not.toHaveProperty('open')
    expect(wrapper.get('[data-test="record-section"]').attributes()).not.toHaveProperty('open')
  })

  it('launches the game and opens its install directory from overview shortcuts', async () => {
    const launch = vi.fn(async () => ok({
      gameId: 'game-1',
      pid: 7,
      launchedAt: '2026-08-14T00:00:00Z',
    }))
    const openDirectory = vi.fn(async () => ok({ opened: true }))
    const bridge = createMockBridge({ launch_game: launch, open_install_directory: openDirectory })
    const wrapper = mount(GameDetailDrawer, {
      props: {
        game: fixtureGame({ mainExeRelpath: 'Alice.exe' }),
        bridge,
      },
    })

    await wrapper.get('[data-test="quick-launch"]').trigger('click')
    await wrapper.get('[data-test="quick-open-directory"]').trigger('click')

    expect(launch).toHaveBeenCalledWith({ gameId: 'game-1' })
    expect(openDirectory).toHaveBeenCalledWith({ gameId: 'game-1' })
  })

  it('shows shortcut failures near the overview actions', async () => {
    const bridge = createMockBridge({
      launch_game: async () => ({
        ok: false,
        error: { code: 'launch_failed', message: '启动失败：主程序不存在' },
      }),
    })
    const wrapper = mount(GameDetailDrawer, {
      props: {
        game: fixtureGame({ mainExeRelpath: 'Alice.exe' }),
        bridge,
      },
    })

    await wrapper.get('[data-test="quick-launch"]').trigger('click')

    expect(wrapper.get('[data-test="quick-message"]').text()).toBe('启动失败：主程序不存在')
  })

  it('shows only one visible close button', () => {
    const wrapper = mount(GameDetailDrawer, {
      props: { game: fixtureGame(), bridge: createMockBridge() },
      attachTo: document.body,
    })

    const closeButtons = wrapper.findAll('button').filter((button) => button.text() === '×')
    expect(closeButtons).toHaveLength(1)
  })

  it('closes from the backdrop', async () => {
    const wrapper = mount(GameDetailDrawer, {
      props: { game: fixtureGame(), bridge: createMockBridge() },
      attachTo: document.body,
    })

    await wrapper.get('[data-test="drawer-backdrop"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('does not mutate page scrollbar compensation', () => {
    document.body.style.paddingRight = '7px'
    const wrapper = mount(GameDetailDrawer, {
      props: { game: fixtureGame(), bridge: createMockBridge() },
      attachTo: document.body,
    })

    expect(document.documentElement.classList.contains('detail-open')).toBe(false)
    expect(document.body.style.paddingRight).toBe('7px')
    wrapper.unmount()
    expect(document.body.style.paddingRight).toBe('7px')
    document.body.style.paddingRight = ''
  })

  it('closes on Escape from anywhere in the window', () => {
    const wrapper = mount(GameDetailDrawer, {
      props: { game: fixtureGame(), bridge: createMockBridge() },
      attachTo: document.body,
    })

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('keeps keyboard focus inside the modal drawer', () => {
    const outside = document.createElement('button')
    document.body.append(outside)
    const wrapper = mount(GameDetailDrawer, {
      props: { game: fixtureGame(), bridge: createMockBridge() },
      attachTo: document.body,
    })
    outside.focus()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', cancelable: true }))

    expect(document.activeElement).toBe(wrapper.get('[data-test="drawer-close"]').element)
  })

  it('includes engine evidence and the manual engine picker', () => {
    const wrapper = mount(GameDetailDrawer, {
      props: {
        game: fixtureGame({
          engineId: 'unity',
          engineLabel: 'Unity',
          detectedEngine: {
            id: 'unity',
            label: 'Unity',
            variant: null,
            confidence: '高',
            evidence: [],
            ambiguous: false,
            experimental: false,
            alternatives: [],
          },
        }),
        bridge: createMockBridge(),
      },
    })

    expect(wrapper.text()).toContain('当前：Unity')
    expect(wrapper.text()).toContain('手动设置引擎')
  })

  it('removes an installed game and adds its root exclusion after confirmation', async () => {
    const bridge = createMockBridge()
    const remove = vi.fn(async () => ok({ removed: true }))
    ;(bridge as GameShelfBridge & { remove_game_and_exclude: typeof remove }).remove_game_and_exclude = remove
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const game = fixtureGame({ status: 'installed' })
    const wrapper = mount(GameDetailDrawer, {
      props: { game, bridge },
      attachTo: document.body,
    })

    await wrapper.get('[data-test="remove-game-and-exclude"]').trigger('click')

    expect(remove).toHaveBeenCalledWith({ gameId: game.id })
    expect(wrapper.emitted('removed')).toEqual([[game.id]])
  })

  it('deletes only a missing game record after confirmation', async () => {
    const bridge = createMockBridge()
    const remove = vi.fn(async () => ok({ removed: true }))
    ;(bridge as GameShelfBridge & { delete_missing_game: typeof remove }).delete_missing_game = remove
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const game = fixtureGame({ status: 'missing', scanRootId: null })
    const wrapper = mount(GameDetailDrawer, {
      props: { game, bridge },
      attachTo: document.body,
    })

    expect(wrapper.find('[data-test="remove-game-and-exclude"]').exists()).toBe(false)
    await wrapper.get('[data-test="delete-missing-game"]').trigger('click')

    expect(remove).toHaveBeenCalledWith({ gameId: game.id })
    expect(wrapper.emitted('removed')).toEqual([[game.id]])
  })
})
