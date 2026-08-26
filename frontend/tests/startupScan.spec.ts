import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import App from '../src/App.vue'
import { bridgeKey } from '../src/api/bridge'
import { createMockBridge, fixtureGame, fixtureRoot, ok } from '../src/api/mockBridge'

describe('startup quick scan', () => {
  it('renders cached games before requesting quick scans for every enabled root', async () => {
    const order: string[] = []
    let wrapper!: VueWrapper
    let renderedWhenScanStarted = false
    const bridge = createMockBridge({
      list_roots: async () => ok([
        fixtureRoot(),
        fixtureRoot({ id: 'root-2', displayPath: 'E:\\Games', pathKey: 'e:\\games' }),
        fixtureRoot({ id: 'root-disabled', enabled: false }),
      ]),
      list_games: async () => {
        order.push('games')
        return ok([fixtureGame({ title: 'Alice' })])
      },
      start_scan: async ({ rootId }) => {
        renderedWhenScanStarted = wrapper.text().includes('Alice')
        order.push(`scan:${rootId}`)
        return ok({ taskId: `task-${rootId}` })
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
    expect(order).toEqual(['games', 'scan:root-1', 'scan:root-2'])
    expect(renderedWhenScanStarted).toBe(true)
  })
})
