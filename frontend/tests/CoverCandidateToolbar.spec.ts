import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { CoverWizardSettings, TaskSnapshot } from '../src/api/contracts'
import { fixtureGame } from '../src/api/mockBridge'
import CoverCandidateToolbar from '../src/features/covers/CoverCandidateToolbar.vue'

const settings: CoverWizardSettings = {
  coverOnlineEnabled: true,
  coverVndbCandidateLimit: 5,
  coverLocalScanCandidateLimit: 10,
  coverOptimizeEnabled: true,
  coverLocalScanDepth: 2,
}

describe('CoverCandidateToolbar', () => {
  it('renders determinate, indeterminate, and completed task progress', async () => {
    const wrapper = mount(CoverCandidateToolbar, {
      props: {
        game: fixtureGame(),
        settings,
        sourceActive: true,
        task: task('running', 4, 12, '正在搜索 5/12：RimWorld'),
        includeUsed: false,
      },
    })

    const progress = wrapper.get('progress')
    expect(progress.attributes('value')).toBe('4')
    expect(progress.attributes('max')).toBe('12')
    expect(wrapper.get('[role="status"]').text()).toContain('4/12')

    await wrapper.setProps({
      task: task('running', 0, null, '正在扫描目录'),
    })
    expect(wrapper.get('progress').attributes('value')).toBeUndefined()
    expect(wrapper.get('[role="status"]').text()).toContain('正在扫描目录')

    await wrapper.setProps({
      task: task('completed', 4, 12, '已完成'),
    })
    expect(wrapper.get('progress').attributes('value')).toBe('12')
    expect(wrapper.get('[role="status"]').text()).toContain('12/12')
  })

  it('uses status-specific fallback messages for empty task messages', async () => {
    const wrapper = mount(CoverCandidateToolbar, {
      props: {
        game: fixtureGame(),
        settings,
        sourceActive: true,
        task: task('running', 0, null, ''),
        includeUsed: false,
      },
    })

    expect(wrapper.get('[role="status"]').text()).toContain('正在收集候选…')
    await wrapper.setProps({ task: task('queued', 0, null, '') })
    expect(wrapper.get('[role="status"]').text()).toContain('正在收集候选…')

    await wrapper.setProps({ task: task('completed', 0, null, '') })
    expect(wrapper.get('[role="status"]').text()).toContain('候选收集完成')
    expect(wrapper.get('[role="status"]').text()).not.toContain('正在收集候选')

    await wrapper.setProps({ task: task('cancelled', 0, null, '') })
    expect(wrapper.get('[role="status"]').text()).toContain('任务已取消')

    const failed = task('failed', 0, null, '')
    failed.error = { code: 'cover_directory_unavailable', message: '目录不可用' }
    await wrapper.setProps({ task: failed })
    expect(wrapper.get('[role="status"]').text()).toContain('目录不可用')
  })

  it('emits the used-directory-candidate toggle', async () => {
    const wrapper = mount(CoverCandidateToolbar, {
      props: {
        game: fixtureGame(),
        settings,
        sourceActive: false,
        task: null,
        includeUsed: false,
      },
    })

    await wrapper.get('[data-test="cover-include-used"]').setValue(true)

    expect(wrapper.emitted('update:includeUsed')).toEqual([[true]])
  })
})

function task(
  status: TaskSnapshot['status'],
  completed: number,
  total: number | null,
  message: string,
): TaskSnapshot {
  return {
    id: 'task-1',
    kind: 'cover-source',
    status,
    progress: { completed, total },
    message,
    result: null,
    error: null,
  }
}
