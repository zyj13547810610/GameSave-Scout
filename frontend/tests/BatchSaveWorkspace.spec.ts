import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMockBridge } from '../src/api/mockBridge'
import BatchSaveWorkspace from '../src/features/saves/BatchSaveWorkspace.vue'
import { useBatchSaveStore } from '../src/features/saves/batchSaveStore'

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
})
