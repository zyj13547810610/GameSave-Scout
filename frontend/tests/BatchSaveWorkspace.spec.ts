import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMockBridge, ok } from '../src/api/mockBridge'
import BatchSaveWorkspace from '../src/features/saves/BatchSaveWorkspace.vue'
import { useBatchSaveStore } from '../src/features/saves/batchSaveStore'
import { fixtureBatchCandidate } from './batchSaveTestFixtures'
import '../src/features/saves/batch-save.css'

beforeEach(() => setActivePinia(createPinia()))

describe('BatchSaveWorkspace', () => {
  it('opens current state on mount and only clears polling on unmount', async () => {
    const store = useBatchSaveStore()
    const open = vi.spyOn(store, 'open').mockResolvedValue(undefined)
    const clear = vi.spyOn(store, 'clearPolling')
    const cancel = vi.spyOn(store, 'cancelScan').mockResolvedValue(undefined)
    const bridge = createMockBridge()

    const wrapper = mount(BatchSaveWorkspace, { props: { bridge } })
    await flushPromises()

    expect(wrapper.get('[data-test="batch-save-workspace"]').text()).toContain('批量存档发现')
    expect(open).toHaveBeenCalledWith(bridge)

    wrapper.unmount()
    expect(clear).toHaveBeenCalled()
    expect(cancel).not.toHaveBeenCalled()
  })

  it('keeps fixed controls around one isolated results scroll region', async () => {
    const wrapper = mount(BatchSaveWorkspace, {
      attachTo: document.body,
      props: { bridge: createMockBridge() },
    })
    await flushPromises()

    const workspace = wrapper.get('[data-test="batch-save-workspace"]')
    const results = wrapper.get('[data-test="batch-save-results"]')
    expect(getComputedStyle(workspace.element).gridTemplateRows).toContain('minmax(0, 1fr)')
    expect(getComputedStyle(workspace.element).overflow).toBe('hidden')
    expect(getComputedStyle(results.element).overflowY).toBe('auto')
    expect(getComputedStyle(results.element).minHeight).toBe('6rem')

    const containerRules = Array.from(document.styleSheets)
      .flatMap((sheet) => Array.from(sheet.cssRules))
      .filter((rule) => rule.cssText.startsWith('@container'))
      .map((rule) => rule.cssText)
      .join(' ')
    expect(containerRules).toContain('max-width: 60rem')
    expect(containerRules).toContain('max-width: 44rem')
    wrapper.unmount()
  })

  it('confirms that candidate rollback removes the whole card but not real saves', async () => {
    const rollback = vi.fn(async () => ok({
      removed: true, restoredCandidateCount: 2,
      removedLocationCount: 2, cleanupWarnings: [],
    }))
    const bridge = createMockBridge({ rollback_batch_save_only_game: rollback })
    const store = useBatchSaveStore()
    vi.spyOn(store, 'open').mockResolvedValue(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    store.page = [fixtureBatchCandidate({
      reviewStatus: 'save_only', reviewGameId: 'save-only-1',
    })]
    store.total = 1
    const wrapper = mount(BatchSaveWorkspace, { props: { bridge } })
    await flushPromises()

    await wrapper.get('[data-test="rollback-save-only-candidate-1"]').trigger('click')
    await flushPromises()

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('删除整张仅存档卡片'))
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('不会删除任何实际存档'))
    expect(rollback).toHaveBeenCalledWith({ candidateId: 'candidate-1' })
    expect(wrapper.emitted('libraryChanged')).toHaveLength(1)
  })
})
