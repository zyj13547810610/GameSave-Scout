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
        libraryScanSettings: { startupQuickScan: true, scanConcurrency: 1 },
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

  it('keeps scan settings fixed above the root scroll region', () => {
    const wrapper = mount(ScanRootList, {
      props: {
        bridge: createMockBridge(),
        roots: [fixtureRoot()],
        libraryScanSettings: { startupQuickScan: true, scanConcurrency: 1 },
        scanTasks: {},
        taskSnapshots: {},
      },
    })

    const panel = wrapper.get('.root-panel')
    const settings = panel.get('[data-test="library-scan-settings"]')
    const scroll = panel.get('[data-test="root-scroll-region"]')
    expect(settings.element.compareDocumentPosition(scroll.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(scroll.find('[data-test="library-scan-settings"]').exists()).toBe(false)
  })

  it('disables manual scanning for a disabled root', () => {
    const wrapper = mount(ScanRootList, {
      props: {
        bridge: createMockBridge(),
        roots: [fixtureRoot({ enabled: false })],
        libraryScanSettings: { startupQuickScan: true, scanConcurrency: 1 },
        scanTasks: {},
        taskSnapshots: {},
      },
    })

    const button = wrapper.get('[data-test="scan-root"]')
    expect(button.attributes('disabled')).toBeDefined()
    expect(button.attributes('title')).toContain('参与扫描')
  })

  it('opens settings for the selected root', async () => {
    const root = fixtureRoot()
    const wrapper = mount(ScanRootList, {
      props: { bridge: createMockBridge(), roots: [root], libraryScanSettings: { startupQuickScan: true, scanConcurrency: 1 }, scanTasks: {}, taskSnapshots: {} },
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
        libraryScanSettings: { startupQuickScan: true, scanConcurrency: 1 },
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

  it('shows determinate quick verification progress and cache counters', () => {
    const root = fixtureRoot()
    const wrapper = mount(ScanRootList, {
      props: {
        bridge: createMockBridge(),
        roots: [root],
        libraryScanSettings: { startupQuickScan: true, scanConcurrency: 1 },
        scanTasks: { [root.id]: 'task-1' },
        taskSnapshots: {
          [root.id]: {
            id: 'task-1', kind: 'library_scan', status: 'running',
            progress: { completed: 8, total: 13 }, message: '已核验：Alice',
            details: {
              stage: 'checking', currentPath: 'Alice', checked: 8,
              cacheHits: 5, reanalyzed: 2, fullAnalyses: 1, warnings: 1,
            },
            result: null, error: null,
          },
        },
      },
    })

    const progress = wrapper.get('[data-test="determinate-progress"]')
    expect(progress.attributes('max')).toBe('13')
    expect(progress.attributes('value')).toBe('8')
    expect(wrapper.get('[data-test="scan-progress"]').text()).toContain('正在核验游戏 8/13')
    expect(wrapper.text()).toContain('Alice')
    expect(wrapper.text()).toContain('复用缓存 5')
    expect(wrapper.text()).toContain('重新分析 2')
    expect(wrapper.text()).toContain('完整分析 1')
    expect(wrapper.text()).toContain('警告 1')
  })

  it('shows determinate full analysis progress after discovery completes', () => {
    const root = fixtureRoot()
    const wrapper = mount(ScanRootList, {
      props: {
        bridge: createMockBridge(),
        roots: [root],
        libraryScanSettings: { startupQuickScan: true, scanConcurrency: 1 },
        scanTasks: { [root.id]: 'task-1' },
        taskSnapshots: {
          [root.id]: {
            id: 'task-1', kind: 'library_scan', status: 'running',
            progress: { completed: 3, total: 13 }, message: '正在分析：Alice',
            details: {
              stage: 'analyzing', currentPath: 'Alice', checked: 3,
              cacheHits: 2, reanalyzed: 0, fullAnalyses: 1, warnings: 0,
              elapsedSeconds: 6.3,
            },
            result: null, error: null,
          },
        },
      },
    })

    expect(wrapper.get('[data-test="scan-progress"]').text()).toContain('正在分析游戏 3/13')
    expect(wrapper.get('[data-test="scan-progress"]').text()).toContain('已用时 6.3 秒')
    expect(wrapper.find('[data-test="determinate-progress"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="indeterminate-progress"]').exists()).toBe(false)
  })

  it('keeps the completed scan summary visible', () => {
    const root = fixtureRoot()
    const wrapper = mount(ScanRootList, {
      props: {
        bridge: createMockBridge(),
        roots: [root],
        libraryScanSettings: { startupQuickScan: true, scanConcurrency: 1 },
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
              added: 2, updated: 1, missing: 1, warnings: 0,
              checked: 4, cacheHits: 2, reanalyzed: 1, fullAnalyses: 1,
              moveSuggestions: [],
            },
            error: null,
          },
        },
      },
    })

    expect(wrapper.get('[data-test="scan-summary"]').text()).toContain('发现 4 · 新增 2 · 更新 1 · 失效 1')
    expect(wrapper.get('[data-test="scan-summary"]').text()).toContain(
      '复用缓存 2 · 重新分析 1 · 完整分析 1 · 警告 0',
    )
    expect(wrapper.text()).toContain('用时 5.5 秒')
  })
})
