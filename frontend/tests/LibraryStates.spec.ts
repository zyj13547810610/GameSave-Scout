import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import App from '../src/App.vue'
import { bridgeKey } from '../src/api/bridge'
import { createMockBridge, fixtureGame, fixtureRoot, ok } from '../src/api/mockBridge'
import GameCard from '../src/features/library/GameCard.vue'
import { useLibraryStore } from '../src/features/library/libraryStore'

describe('library states', () => {
  it('renders the empty library state', async () => {
    const wrapper = mountApp(createMockBridge(), createPinia())
    await flushPromises()
    expect(wrapper.text()).toContain('还没有添加游戏目录')
  })

  it('renders the no-results state without removing the library', async () => {
    const pinia = createPinia()
    const wrapper = mountApp(createMockBridge({
      list_games: async () => ok([fixtureGame()]),
    }), pinia)
    await flushPromises()
    useLibraryStore(pinia).query = '不存在的标题'
    await flushPromises()
    expect(wrapper.text()).toContain('没有符合筛选条件的游戏')
  })

  it('keeps a clear root-unavailable message', async () => {
    const pinia = createPinia()
    const wrapper = mountApp(createMockBridge({
      list_roots: async () => ok([fixtureRoot({ lastScanStatus: 'unavailable' })]),
      list_games: async () => ok([fixtureGame()]),
    }), pinia)
    await flushPromises()
    useLibraryStore(pinia).fail('根目录暂时无法访问，已有游戏状态未改变')
    await flushPromises()
    expect(wrapper.text()).toContain('已有游戏状态未改变')
    expect(wrapper.text()).toContain('Alice')
  })

  it('renders a broken-cover fallback', async () => {
    const wrapper = mount(GameCard, {
      props: { game: fixtureGame({ coverThumbUrl: '/broken.webp' }) },
    })
    await wrapper.get('img').trigger('error')
    expect(wrapper.text()).toContain('封面加载失败')
  })
})

function mountApp(bridge: ReturnType<typeof createMockBridge>, pinia: ReturnType<typeof createPinia>) {
  return mount(App, {
    global: { plugins: [pinia], provide: { [bridgeKey as symbol]: bridge } },
  })
}
