import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
import { bridgeKey } from '../src/api/bridge'
import type { UiScaleValue } from '../src/api/contracts'
import { createMockBridge, fixtureGame, ok } from '../src/api/mockBridge'
import '../src/styles/base.css'

beforeEach(() => {
  localStorage.clear()
  document.documentElement.style.removeProperty('--ui-scale')
})

describe('App', () => {
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
        return ok({ appName: 'GameShelf', schemaVersion: 1, portable: true, uiScale: 1.2 })
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
})
