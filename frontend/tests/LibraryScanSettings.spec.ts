import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMockBridge, ok } from '../src/api/mockBridge'
import LibraryScanSettings from '../src/features/scan-roots/LibraryScanSettings.vue'

describe('LibraryScanSettings', () => {
  it('saves the complete controlled settings and emits the committed value', async () => {
    const save = vi.fn(async () => ok({ startupQuickScan: false, scanConcurrency: 1 as const }))
    const wrapper = mount(LibraryScanSettings, {
      props: {
        bridge: createMockBridge({ set_library_scan_settings: save }),
        settings: { startupQuickScan: true, scanConcurrency: 1 },
      },
    })

    expect(wrapper.text()).toContain('启动时快速核验')
    expect(wrapper.get('[data-test="scan-concurrency"]').element).toMatchObject({ value: '1' })
    await wrapper.get('[data-test="startup-quick-scan"]').setValue(false)
    await flushPromises()

    expect(save).toHaveBeenCalledWith({ startupQuickScan: false, scanConcurrency: 1 })
    expect(wrapper.emitted('updated')).toEqual([[
      { startupQuickScan: false, scanConcurrency: 1 },
    ]])
  })

  it('restores the last successful value and shows an error when saving fails', async () => {
    const wrapper = mount(LibraryScanSettings, {
      props: {
        bridge: createMockBridge({
          async set_library_scan_settings() {
            return { ok: false, error: { code: 'config_save_failed', message: '扫描设置保存失败' } }
          },
        }),
        settings: { startupQuickScan: true, scanConcurrency: 1 },
      },
    })

    await wrapper.get('[data-test="scan-concurrency"]').setValue('4')
    await flushPromises()

    expect(wrapper.get('[data-test="scan-concurrency"]').element).toMatchObject({ value: '1' })
    expect(wrapper.get('[data-test="scan-settings-error"]').text()).toBe('扫描设置保存失败')
    expect(wrapper.emitted('updated')).toBeUndefined()
  })
})
