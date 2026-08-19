import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import type { TaskSnapshot } from '../src/api/contracts'
import BatchSaveStatusBar from '../src/features/saves/BatchSaveStatusBar.vue'
import { useBatchSaveStore } from '../src/features/saves/batchSaveStore'

beforeEach(() => setActivePinia(createPinia()))

describe('BatchSaveStatusBar', () => {
  it('offers a return entry only while a scan is active', async () => {
    const store = useBatchSaveStore()
    store.task = fixtureTask({ status: 'running', message: '正在扫描 Documents' })
    const wrapper = mount(BatchSaveStatusBar)

    expect(wrapper.text()).toContain('批量存档扫描正在运行')
    expect(wrapper.text()).toContain('正在扫描 Documents')
    await wrapper.get('[data-test="restore-batch-save"]').trigger('click')
    expect(wrapper.emitted('restore')).toEqual([[]])

    store.task = fixtureTask({ status: 'completed' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-test="batch-save-status-bar"]').exists()).toBe(false)
  })
})

function fixtureTask(overrides: Partial<TaskSnapshot> = {}): TaskSnapshot {
  return {
    id: 'batch-task-1', kind: 'batch_save_scan', status: 'queued',
    progress: { completed: 0, total: null }, message: '', result: null, error: null,
    ...overrides,
  }
}
