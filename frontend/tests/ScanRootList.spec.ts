import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMockBridge, fixtureRoot } from '../src/api/mockBridge'
import ScanRootList from '../src/features/scan-roots/ScanRootList.vue'
import '../src/styles/base.css'

describe('ScanRootList', () => {
  it('keeps the title outside one scroll region containing every root card', () => {
    const wrapper = mount(ScanRootList, {
      attachTo: document.body,
      props: {
        bridge: createMockBridge(),
        roots: [fixtureRoot()],
        scanTasks: {},
        taskSnapshots: {},
      },
    })

    const region = wrapper.get('[data-test="root-scroll-region"]')
    expect(wrapper.get('.root-panel > h2').text()).toBe('游戏目录')
    expect(region.find('.root-item').exists()).toBe(true)
    expect(getComputedStyle(region.element).overflowY).toBe('auto')
    wrapper.unmount()
  })

  it('opens settings for the selected root', async () => {
    const root = fixtureRoot()
    const wrapper = mount(ScanRootList, {
      props: { bridge: createMockBridge(), roots: [root], scanTasks: {}, taskSnapshots: {} },
    })

    await wrapper.get('[data-test="edit-root"]').trigger('click')

    expect(wrapper.emitted('edit')).toEqual([[root]])
  })

  it('shows structured indeterminate progress for an active scan', () => {
    const root = fixtureRoot()
    const wrapper = mount(ScanRootList, {
      props: {
        bridge: createMockBridge(),
        roots: [root],
        scanTasks: { [root.id]: 'task-1' },
        taskSnapshots: {
          [root.id]: {
            id: 'task-1',
            kind: 'library_scan',
            status: 'running',
            progress: { completed: 3, total: null },
            message: '正在检查：Group/GameC',
            details: {
              stage: 'discovering',
              currentPath: 'Group/GameC',
              directoriesScanned: 12,
              discovered: 3,
              inaccessibleDirectories: 1,
              warnings: 2,
              elapsedSeconds: 4.2,
            },
            result: null,
            error: null,
          },
        },
      },
    })

    expect(wrapper.get('[data-test="scan-progress"]').text()).toContain('正在查找游戏')
    expect(wrapper.text()).toContain('Group/GameC')
    expect(wrapper.text()).toContain('已检查 12 个目录')
    expect(wrapper.text()).toContain('发现 3 个游戏')
    expect(wrapper.text()).toContain('不可访问 1 个')
    expect(wrapper.text()).toContain('警告 2 项')
    expect(wrapper.text()).toContain('4.2 秒')
    expect(wrapper.find('[data-test="indeterminate-progress"]').exists()).toBe(true)
  })

  it('keeps the completed scan summary visible', () => {
    const root = fixtureRoot()
    const wrapper = mount(ScanRootList, {
      props: {
        bridge: createMockBridge(),
        roots: [root],
        scanTasks: {},
        taskSnapshots: {
          [root.id]: {
            id: 'task-1',
            kind: 'library_scan',
            status: 'completed',
            progress: { completed: 4, total: null },
            message: '扫描完成。',
            details: { stage: 'completed', elapsedSeconds: 5.5 },
            result: {
              sessionId: 'scan-1', status: 'completed', discovered: 4,
              added: 2, updated: 1, missing: 1, warnings: 0, moveSuggestions: [],
            },
            error: null,
          },
        },
      },
    })

    expect(wrapper.get('[data-test="scan-summary"]').text()).toContain('发现 4 · 新增 2 · 更新 1 · 失效 1')
    expect(wrapper.text()).toContain('用时 5.5 秒')
  })
})
