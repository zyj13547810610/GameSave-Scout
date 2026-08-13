import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMockBridge, fixtureRoot } from '../src/api/mockBridge'
import ScanRootList from '../src/features/scan-roots/ScanRootList.vue'

describe('ScanRootList', () => {
  it('opens settings for the selected root', async () => {
    const root = fixtureRoot()
    const wrapper = mount(ScanRootList, {
      props: { bridge: createMockBridge(), roots: [root], scanTasks: {} },
    })

    await wrapper.get('[data-test="edit-root"]').trigger('click')

    expect(wrapper.emitted('edit')).toEqual([[root]])
  })
})
