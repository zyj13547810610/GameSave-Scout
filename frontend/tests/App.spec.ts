import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import App from '../src/App.vue'

describe('App', () => {
  it('renders the product name and empty-library message', () => {
    const wrapper = mount(App)
    expect(wrapper.get('h1').text()).toBe('GameShelf')
    expect(wrapper.text()).toContain('还没有添加游戏目录')
  })
})
