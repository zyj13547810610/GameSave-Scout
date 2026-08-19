import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import BatchManagementBar from '../src/features/library/BatchManagementBar.vue'

describe('BatchManagementBar', () => {
  it('shows all status counts and protects deletion when save-only games are selected', async () => {
    const wrapper = mount(BatchManagementBar, {
      props: {
        selectedCount: 3,
        installedCount: 1,
        missingCount: 1,
        saveOnlyCount: 1,
        busy: false,
        canSelectVisible: true,
        canRemove: false,
      },
    })

    expect(wrapper.get('[data-test="batch-counts"]').text()).toContain('已选择 3 个')
    expect(wrapper.get('[data-test="batch-counts"]').text()).toContain('已安装 1')
    expect(wrapper.get('[data-test="batch-counts"]').text()).toContain('失效 1')
    expect(wrapper.get('[data-test="batch-counts"]').text()).toContain('仅存档 1')
    expect(wrapper.get('[data-test="batch-delete"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="batch-delete"]').attributes('title')).toBe(
      '仅存档记录不能通过批量移除删除',
    )
    expect(wrapper.text()).toContain('仅存档记录不能通过批量移除删除')
    expect(wrapper.get('[data-test="batch-group"]').attributes('disabled')).toBeUndefined()

    await wrapper.get('[data-test="batch-group"]').trigger('click')
    expect(wrapper.emitted('group')).toHaveLength(1)
  })

  it('keeps deletion available for an installed and missing selection', () => {
    const wrapper = mount(BatchManagementBar, {
      props: {
        selectedCount: 2,
        installedCount: 1,
        missingCount: 1,
        saveOnlyCount: 0,
        busy: false,
        canSelectVisible: true,
        canRemove: true,
      },
    })

    expect(wrapper.get('[data-test="batch-delete"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-test="batch-delete"]').attributes('title')).toBeUndefined()
  })
})
