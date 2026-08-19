import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMockBridge, ok } from '../src/api/mockBridge'
import BatchSaveFilters from '../src/features/saves/BatchSaveFilters.vue'
import { useBatchSaveStore } from '../src/features/saves/batchSaveStore'

beforeEach(() => setActivePinia(createPinia()))

describe('BatchSaveFilters', () => {
  it('offers all eight statuses and composes filters with paging', async () => {
    const list = vi.fn(async () => ok({ items: [], total: 120 }))
    const bridge = createMockBridge({ list_batch_save_candidates: list })
    const store = useBatchSaveStore()
    store.total = 120
    const wrapper = mount(BatchSaveFilters, { props: { bridge } })

    expect(wrapper.findAll('[data-test="batch-status-filter"] option')).toHaveLength(8)
    await wrapper.get('[data-test="batch-status-filter"]').setValue('missing')
    await wrapper.get('[data-test="batch-confidence-filter"]').setValue('medium')
    await wrapper.get('[data-test="batch-source-filter"]').setValue('engine')
    await wrapper.get('[data-test="batch-keyword-filter"]').setValue('Alice')
    await wrapper.get('[data-test="batch-filter-form"]').trigger('submit')
    await flushPromises()

    expect(list).toHaveBeenLastCalledWith({
      status: 'missing', keyword: 'Alice', confidence: 'medium', source: 'engine',
      offset: 0, limit: 50,
    })
    await wrapper.get('[data-test="batch-next-page"]').trigger('click')
    await flushPromises()
    expect(store.filters.offset).toBe(50)
  })
})
