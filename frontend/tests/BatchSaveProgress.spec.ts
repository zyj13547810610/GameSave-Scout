import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import BatchSaveProgress from '../src/features/saves/BatchSaveProgress.vue'
import { fixtureBatchTask } from './batchSaveTestFixtures'

describe('BatchSaveProgress', () => {
  it('shows phase metadata and exposes cancellation for active tasks', async () => {
    const task = fixtureBatchTask({
      details: {
        phase: 'filesystem', currentScope: 'Documents', currentDirectory: 'C:\\Users\\Alice',
        entriesVisited: 120, candidateCount: 4, elapsedSeconds: 3.5,
      },
    })
    const wrapper = mount(BatchSaveProgress, { props: { task, busy: false } })

    expect(wrapper.text()).toContain('Documents')
    expect(wrapper.text()).toContain('120')
    expect(wrapper.text()).toContain('4')
    expect(wrapper.text()).toContain('3.5 秒')
    await wrapper.get('[data-test="cancel-batch-scan"]').trigger('click')
    expect(wrapper.emitted('cancel')).toEqual([[]])
  })

  it('renders a complete zero-candidate summary', () => {
    const wrapper = mount(BatchSaveProgress, {
      props: {
        busy: false,
        task: fixtureBatchTask({
          status: 'completed', progress: { completed: 1, total: 1 },
          message: '未发现存档候选',
          result: {
            sessionId: 'session-1', status: 'completed', newCount: 0, pendingCount: 0,
            recordedCount: 0, ignoredCount: 0, unavailableCount: 0, groupCount: 0,
            inaccessibleScopeCount: 1, truncatedScopeCount: 1, totalEntries: 10,
            elapsedSeconds: 2.4,
          },
        }),
      },
    })

    expect(wrapper.text()).toContain('未发现存档候选')
    expect(wrapper.text()).toContain('不可访问范围 1')
    expect(wrapper.text()).toContain('截断范围 1')
  })
})
