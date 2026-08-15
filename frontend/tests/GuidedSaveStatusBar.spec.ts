import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import type { GuidedSaveSession } from '../src/api/contracts'
import GuidedSaveStatusBar from '../src/features/saves/GuidedSaveStatusBar.vue'
import { useGuidedSaveStore } from '../src/features/saves/guidedSaveStore'

beforeEach(() => setActivePinia(createPinia()))

describe('GuidedSaveStatusBar', () => {
  it('shows only active sessions without exposing file paths', async () => {
    const store = useGuidedSaveStore()
    store.session = fixtureSession()
    const wrapper = mount(GuidedSaveStatusBar)

    expect(wrapper.text()).toContain('正在为《Alice》寻找存档')
    expect(wrapper.text()).toContain('监控中')
    expect(wrapper.text()).not.toContain('D:\\Games')

    await wrapper.get('[data-test="restore-guided-save"]').trigger('click')
    expect(wrapper.emitted('restore')).toEqual([['game-1']])
  })

  it('hides after a session reaches a terminal state', async () => {
    const store = useGuidedSaveStore()
    store.session = fixtureSession({ status: 'completed' })
    const wrapper = mount(GuidedSaveStatusBar)

    expect(wrapper.find('[data-test="guided-save-status-bar"]').exists()).toBe(false)
  })
})

function fixtureSession(overrides: Partial<GuidedSaveSession> = {}): GuidedSaveSession {
  return {
    id: 'session-1', gameId: 'game-1', gameTitle: 'Alice', status: 'monitoring',
    startedAt: '2026-08-15T00:00:00+00:00', monitoringStartedAt: '2026-08-15T00:00:01+00:00',
    saveMarkedAt: null, finishedAt: null, changeCount: 1, processTrackingDegraded: false,
    overflowedScopes: [], truncatedScopes: [], closeRequested: false, error: null,
    ...overrides,
  }
}
