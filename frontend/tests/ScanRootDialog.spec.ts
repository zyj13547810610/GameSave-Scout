import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMockBridge } from '../src/api/mockBridge'
import ScanRootDialog from '../src/features/scan-roots/ScanRootDialog.vue'

describe('ScanRootDialog', () => {
  it('validates recursive depth before calling the bridge', async () => {
    const bridge = createMockBridge()
    const addRoot = vi.spyOn(bridge, 'add_root')
    const wrapper = mount(ScanRootDialog, { props: { bridge } })
    await wrapper.get('[data-test="display-path"]').setValue('D:\\Games')
    await wrapper.get('[data-test="mode-recursive"]').setValue(true)
    await wrapper.get('[data-test="max-depth"]').setValue(9)
    await wrapper.get('form').trigger('submit')

    expect(wrapper.text()).toContain('扫描深度必须在 1 到 8 之间')
    expect(addRoot).not.toHaveBeenCalled()
  })
})
