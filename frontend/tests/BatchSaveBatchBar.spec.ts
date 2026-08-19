import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import BatchSaveBatchBar from '../src/features/saves/BatchSaveBatchBar.vue'
import { fixtureBatchCandidate } from './batchSaveTestFixtures'

describe('BatchSaveBatchBar', () => {
  it('summarizes selected types and emits batch actions without overlay positioning', async () => {
    const selected = [
      fixtureBatchCandidate(),
      fixtureBatchCandidate({ id: 'file-1', kind: 'file' }),
      fixtureBatchCandidate({ id: 'registry-1', kind: 'registry' }),
    ]
    const wrapper = mount(BatchSaveBatchBar, { props: { selected, busy: false } })

    expect(wrapper.text()).toContain('已选择 3')
    expect(wrapper.text()).toContain('目录 1')
    expect(wrapper.text()).toContain('文件 1')
    expect(wrapper.text()).toContain('注册表 1')
    await wrapper.get('[data-test="accept-selected-candidates"]').trigger('click')
    expect(wrapper.emitted('accept')).toEqual([[]])
    expect(wrapper.classes()).not.toContain('fixed')
  })
})
