import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import App from '../src/App.vue'

describe('App', () => {
  it('connects before rendering the empty-library message', async () => {
    const wrapper = mount(App, { global: { plugins: [createPinia()] } })
    expect(wrapper.get('h1').text()).toBe('GameShelf')
    expect(wrapper.text()).toContain('正在连接本地数据库…')

    await flushPromises()

    expect(wrapper.text()).toContain('还没有添加游戏目录')
  })
})
