import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import App from '../src/App.vue'
import { bridgeKey } from '../src/api/bridge'
import { createMockBridge, fixtureGame, ok } from '../src/api/mockBridge'
import { UI_SCALE_STORAGE_KEY } from '../src/features/preferences/uiScale'
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

  it('restores and persists the selected UI scale', async () => {
    localStorage.setItem(UI_SCALE_STORAGE_KEY, '1.2')
    const wrapper = mount(App, { global: { plugins: [createPinia()] } })

    expect(document.documentElement.style.getPropertyValue('--ui-scale')).toBe('1.2')
    await wrapper.get('[data-test="ui-scale"]').setValue('1.3')

    expect(document.documentElement.style.getPropertyValue('--ui-scale')).toBe('1.3')
    expect(localStorage.getItem(UI_SCALE_STORAGE_KEY)).toBe('1.3')
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
