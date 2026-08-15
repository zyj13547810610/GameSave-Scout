import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { GuidedSaveDiscovery } from '../src/api/contracts'
import { createMockBridge, fixtureGuidedSession, ok } from '../src/api/mockBridge'
import GuidedSaveDiscoveries from '../src/features/saves/GuidedSaveDiscoveries.vue'
import { useGuidedSaveStore } from '../src/features/saves/guidedSaveStore'

beforeEach(() => setActivePinia(createPinia()))

describe('GuidedSaveDiscoveries', () => {
  it('groups candidates and only preselects safe marked filesystem results', () => {
    const store = seed([
      fixtureDiscovery({ id: 'high', confidence: 0.92, preselected: true }),
      fixtureDiscovery({ id: 'overflow', confidence: 0.9, preselected: true, affectedByOverflow: true }),
      fixtureDiscovery({ id: 'unmarked', confidence: 0.8, preselected: true, markOffsetMs: null }),
      fixtureDiscovery({ id: 'low', confidence: 0.4, preselected: false }),
      fixtureDiscovery({ id: 'registry', kind: 'registry', preselected: true }),
    ])
    const wrapper = mount(GuidedSaveDiscoveries, {
      props: { bridge: createMockBridge() },
    })

    expect(wrapper.text()).toContain('高可信候选')
    expect(wrapper.text()).toContain('中可信候选')
    expect(wrapper.text()).toContain('低可信候选')
    expect(wrapper.text()).toContain('注册表候选')
    expect(checked(wrapper, 'high')).toBe(true)
    expect(checked(wrapper, 'overflow')).toBe(false)
    expect(checked(wrapper, 'unmarked')).toBe(false)
    expect(checked(wrapper, 'registry')).toBe(false)
    expect(store.discoveries).toHaveLength(5)
  })

  it('requires registry confirmation and emits after a successful accept', async () => {
    seed([fixtureDiscovery({ id: 'registry', kind: 'registry', preselected: false })])
    const accept = vi.fn(async () => ok([]))
    const bridge = createMockBridge({
      accept_guided_save_discoveries: accept,
      async list_guided_save_discoveries() { return ok([]) },
    })
    const wrapper = mount(GuidedSaveDiscoveries, { props: { bridge } })
    await wrapper.get('[data-test="guided-discovery-registry"]').setValue(true)

    vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
    await wrapper.get('[data-test="accept-guided-discoveries"]').trigger('click')
    expect(accept).not.toHaveBeenCalled()

    vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
    await wrapper.get('[data-test="accept-guided-discoveries"]').trigger('click')
    await flushPromises()

    expect(accept).toHaveBeenCalledWith({
      sessionId: 'session-1',
      discoveryIds: ['registry'],
      confirmRegistry: true,
    })
    expect(wrapper.emitted('accepted')).toHaveLength(1)
  })

  it('confirms before discarding all unreviewed results', async () => {
    seed([fixtureDiscovery()])
    const discard = vi.fn(async () => ok({ discarded: 1 }))
    const wrapper = mount(GuidedSaveDiscoveries, {
      props: { bridge: createMockBridge({ discard_guided_save_detection: discard }) },
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    await wrapper.get('[data-test="discard-guided-discoveries"]').trigger('click')
    await flushPromises()

    expect(discard).toHaveBeenCalledWith({ sessionId: 'session-1' })
  })

  it('shows session-level overflow and incomplete-scope warnings', () => {
    const store = seed([])
    store.session = fixtureGuidedSession({
      id: 'session-1',
      status: 'completed',
      overflowedScopes: ['D:\\Games\\Alice'],
      truncatedScopes: ['D:\\Users\\Alice\\AppData\\Local'],
    })

    const wrapper = mount(GuidedSaveDiscoveries, {
      props: { bridge: createMockBridge() },
    })

    expect(wrapper.text()).toContain('部分监控事件曾溢出')
    expect(wrapper.text()).toContain('部分监控范围的结果不完整')
  })
})

function seed(discoveries: GuidedSaveDiscovery[]) {
  const store = useGuidedSaveStore()
  store.session = fixtureGuidedSession({ id: 'session-1', status: 'completed' })
  store.discoveries = discoveries
  return store
}

function checked(wrapper: ReturnType<typeof mount>, id: string): boolean {
  return (wrapper.get(`[data-test="guided-discovery-${id}"]`).element as HTMLInputElement).checked
}

function fixtureDiscovery(overrides: Partial<GuidedSaveDiscovery> = {}): GuidedSaveDiscovery {
  return {
    id: 'high', sessionId: 'session-1', candidateTemplate: '<game>\\Saves',
    displayPath: 'D:\\Games\\Alice\\Saves', kind: 'directory', confidence: 0.92,
    evidence: ['保存标记前后发生协调变化'], representativeFiles: ['slot1.sav'],
    firstChangedAt: '2026-08-15T00:00:05+00:00', lastChangedAt: '2026-08-15T00:00:11+00:00',
    markOffsetMs: 1000, affectedByOverflow: false, affectedByTruncation: false,
    preselected: true, reviewStatus: 'unreviewed', saveLocationId: null,
    ...overrides,
  }
}
