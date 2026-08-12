import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import App from '../src/App.vue'
import { bridgeKey } from '../src/api/bridge'
import { createMockBridge, fixtureGame, fixtureRoot, ok } from '../src/api/mockBridge'

describe('startup quick scan', () => {
  it('renders cached games before requesting quick scans', async () => {
    const order: string[] = []
    let wrapper!: VueWrapper
    let renderedWhenScanStarted = false
    const bridge = createMockBridge({
      list_roots: async () => ok([fixtureRoot()]),
      list_games: async () => {
        order.push('games')
        return ok([fixtureGame({ title: 'Alice' })])
      },
      start_scan: async () => {
        renderedWhenScanStarted = wrapper.text().includes('Alice')
        order.push('scan')
        return ok({ taskId: 'task-1' })
      },
    })
    wrapper = mount(App, {
      global: {
        plugins: [createPinia()],
        provide: { [bridgeKey as symbol]: bridge },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('Alice')
    expect(order).toEqual(['games', 'scan'])
    expect(renderedWhenScanStarted).toBe(true)
  })
})
