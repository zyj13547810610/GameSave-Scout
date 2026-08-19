import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMockBridge, ok } from '../src/api/mockBridge'
import BatchSaveSettings from '../src/features/saves/BatchSaveSettings.vue'

beforeEach(() => vi.restoreAllMocks())

describe('BatchSaveSettings', () => {
  it('defaults five standard scopes without starting a scan and persists custom roots only', async () => {
    const start = vi.fn()
    const add = vi.fn(async () => ok({
      id: 'custom-1', displayPath: 'D:\\Save Archive', enabled: true, maxDepth: 6,
    }))
    const bridge = createMockBridge({
      async bootstrap() {
        return ok({
          appName: 'GameShelf', schemaVersion: 4, portable: true, uiScale: 1,
          coverWizardSettings: { coverOnlineEnabled: false, coverVndbCandidateLimit: 5, coverLocalScanCandidateLimit: 10 },
          libraryScanSettings: { startupQuickScan: true, scanConcurrency: 1 },
          batchSaveSettings: { customRoots: [] },
        })
      },
      async choose_batch_save_custom_root() { return ok('D:\\Save Archive') },
      add_batch_save_custom_root: add,
      start_batch_save_scan: start,
    })
    const wrapper = mount(BatchSaveSettings, { props: { bridge, active: false } })
    await flushPromises()

    expect(wrapper.findAll('.standard-scope-checkbox')).toHaveLength(5)
    expect(wrapper.findAll<HTMLInputElement>('.standard-scope-checkbox').every((item) => item.element.checked)).toBe(true)
    expect(start).not.toHaveBeenCalled()

    await wrapper.get('[data-test="add-batch-root"]').trigger('click')
    await flushPromises()
    expect(add).toHaveBeenCalledWith({ displayPath: 'D:\\Save Archive', enabled: true, maxDepth: 6 })
    expect(wrapper.text()).toContain('D:\\Save Archive')
  })

  it('confirms the selected scopes and locks settings while active', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(BatchSaveSettings, {
      props: { bridge: createMockBridge(), active: false },
    })
    await flushPromises()
    await wrapper.get('[data-test="standard-app_data"]').setValue(false)
    await wrapper.get('[data-test="start-batch-scan"]').trigger('click')

    expect(wrapper.emitted('start')?.[0]).toEqual([[
      'documents', 'saved_games', 'local_app_data', 'local_app_data_low',
    ], []])

    await wrapper.setProps({ active: true })
    expect(wrapper.get('[data-test="standard-documents"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="start-batch-scan"]').attributes('disabled')).toBeDefined()
  })
})
