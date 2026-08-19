import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMockBridge } from '../src/api/mockBridge'
import BatchSaveWorkspace from '../src/features/saves/BatchSaveWorkspace.vue'
import { useBatchSaveStore } from '../src/features/saves/batchSaveStore'
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
})
