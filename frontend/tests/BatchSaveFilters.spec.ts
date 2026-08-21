import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMockBridge, ok } from '../src/api/mockBridge'
import BatchSaveFilters from '../src/features/saves/BatchSaveFilters.vue'
import { useBatchSaveStore } from '../src/features/saves/batchSaveStore'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.useRealTimers())

describe('BatchSaveFilters', () => {
  it('offers all eight statuses and applies select filters immediately', async () => {
    const list = vi.fn(async () => ok({ items: [], total: 120 }))
    const bridge = createMockBridge({ list_batch_save_candidates: list })
    const store = useBatchSaveStore()
    store.total = 120
    store.filters.offset = 50
    const wrapper = mount(BatchSaveFilters, { props: { bridge } })

    expect(wrapper.findAll('[data-test="batch-status-filter"] option')).toHaveLength(8)
    expect(wrapper.get('[data-test="batch-status-filter"]').text()).toContain('未关联游戏')
    expect(wrapper.get('[data-test="batch-source-filter"]').text()).toContain('内置规则')
    expect(wrapper.find('button[type="submit"]').exists()).toBe(false)
    await wrapper.get('[data-test="batch-status-filter"]').setValue('missing')
    await flushPromises()

    expect(list).toHaveBeenLastCalledWith({
      status: 'missing', keyword: '', confidence: 'all', source: 'all',
      offset: 0, limit: 50,
    })

    await wrapper.get('[data-test="batch-confidence-filter"]').setValue('medium')
    await wrapper.get('[data-test="batch-source-filter"]').setValue('builtin')
    await flushPromises()

    expect(list).toHaveBeenLastCalledWith({
      status: 'missing', keyword: '', confidence: 'medium', source: 'builtin',
      offset: 0, limit: 50,
    })
    await wrapper.get('[data-test="batch-next-page"]').trigger('click')
    await flushPromises()
    expect(store.filters.offset).toBe(50)
  })

  it('debounces keyword filtering for 300ms and submits immediately on Enter', async () => {
    vi.useFakeTimers()
    const list = vi.fn(async () => ok({ items: [], total: 1 }))
    const bridge = createMockBridge({ list_batch_save_candidates: list })
    const wrapper = mount(BatchSaveFilters, { props: { bridge } })

    await wrapper.get('[data-test="batch-keyword-filter"]').setValue('Alice')
    await vi.advanceTimersByTimeAsync(299)
    expect(list).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()
    expect(list).toHaveBeenCalledTimes(1)

    await wrapper.get('[data-test="batch-keyword-filter"]').setValue('Bob')
    await wrapper.get('[data-test="batch-filter-form"]').trigger('submit')
    await flushPromises()
    expect(list).toHaveBeenCalledTimes(2)
    expect(list).toHaveBeenLastCalledWith({
      status: 'all', keyword: 'Bob', confidence: 'all', source: 'all',
      offset: 0, limit: 50,
    })
    await vi.advanceTimersByTimeAsync(300)
    expect(list).toHaveBeenCalledTimes(2)
  })
})
