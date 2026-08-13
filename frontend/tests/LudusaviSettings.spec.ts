import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMockBridge, ok } from '../src/api/mockBridge'
import LudusaviSettings from '../src/features/saves/LudusaviSettings.vue'

enableAutoUnmount(afterEach)
afterEach(() => vi.useRealTimers())

describe('LudusaviSettings', () => {
  it('shows fixed snapshot metadata and only updates after an explicit click', async () => {
    const update = vi.fn(async () => ok({ taskId: 'task-1' }))
    const bridge = createMockBridge({
      ludusavi_status: async () => ok({
        available: true,
        unavailableReason: null,
        sourceUrl: 'https://example.test/manifest.yaml',
        downloadedAt: '2026-08-12T00:00:00+00:00',
        sha256: '1234567890abcdef'.repeat(4),
        etag: '"etag"',
        customDirectory: 'D:\\GameShelf\\data\\manifests\\custom',
        customErrors: [],
      }),
      update_ludusavi: update,
    })
    const wrapper = mount(LudusaviSettings, { props: { bridge } })
    await flushPromises()

    expect(wrapper.text()).toContain('1234567890ab')
    expect(wrapper.text()).not.toContain('自动更新')
    expect(update).not.toHaveBeenCalled()
    await wrapper.get('[data-test="update-ludusavi"]').trigger('click')
    expect(update).toHaveBeenCalledTimes(1)
  })

  it('opens the custom manifest directory on request', async () => {
    const open = vi.fn(async () => ok({ opened: true }))
    const bridge = createMockBridge({ open_custom_manifest_directory: open })
    const wrapper = mount(LudusaviSettings, { props: { bridge } })
    await flushPromises()

    await wrapper.get('[data-test="open-custom-manifests"]').trigger('click')
    expect(open).toHaveBeenCalledTimes(1)
  })

  it('shows the provider result after the update task completes', async () => {
    const bridge = createMockBridge({
      update_ludusavi: async () => ok({ taskId: 'task-1' }),
      task_snapshot: async () => ok({
        id: 'task-1',
        kind: 'ludusavi_update',
        status: 'completed',
        progress: { completed: 1, total: 1 },
        message: 'Ludusavi 清单已是最新。',
        result: {
          status: 'not_modified',
          message: 'Ludusavi 清单已是最新。',
          metadata: null,
        },
        error: null,
      }),
    })
    const wrapper = mount(LudusaviSettings, { props: { bridge } })
    await flushPromises()

    await wrapper.get('[data-test="update-ludusavi"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Ludusavi 清单已是最新。')
    expect(wrapper.get('[data-test="ludusavi-result"]').classes()).toContain('not_modified')
  })

  it('shows that the last valid manifest remains active after an update failure', async () => {
    const bridge = createMockBridge({
      ludusavi_status: async () => ok({
        available: true,
        unavailableReason: null,
        sourceUrl: 'https://example.test/manifest.yaml',
        downloadedAt: '2026-08-12T00:00:00+00:00',
        sha256: '1234567890abcdef'.repeat(4),
        etag: '"etag"',
        upstreamCommit: null,
        customDirectory: 'D:\\GameShelf\\data\\manifests\\custom',
        customErrors: [],
      }),
      update_ludusavi: async () => ok({ taskId: 'task-1' }),
      task_snapshot: async () => ok({
        id: 'task-1',
        kind: 'ludusavi_update',
        status: 'completed',
        progress: { completed: 1, total: 1 },
        message: '网络连接失败。当前有效清单仍可使用。',
        result: {
          status: 'failed',
          message: '网络连接失败。当前有效清单仍可使用。',
          metadata: null,
        },
        error: null,
      }),
    })
    const wrapper = mount(LudusaviSettings, { props: { bridge } })
    await flushPromises()

    await wrapper.get('[data-test="update-ludusavi"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="ludusavi-result"]').classes()).toContain('failed')
    expect(wrapper.text()).toContain('当前有效清单仍可使用')
    expect(wrapper.text()).toContain('1234567890ab')
  })

  it('shows unavailable official rules while leaving retry enabled', async () => {
    const bridge = createMockBridge({
      ludusavi_status: async () => ok({
        available: false,
        unavailableReason: '内置清单损坏',
        sourceUrl: null,
        downloadedAt: null,
        sha256: null,
        etag: null,
        upstreamCommit: null,
        customDirectory: 'D:\\GameShelf\\data\\manifests\\custom',
        customErrors: [],
      }),
    })
    const wrapper = mount(LudusaviSettings, { props: { bridge } })
    await flushPromises()

    expect(wrapper.text()).toContain('Ludusavi 官方规则暂不可用')
    expect(wrapper.text()).toContain('内置清单损坏')
    expect(wrapper.get('[data-test="update-ludusavi"]').attributes('disabled')).toBeUndefined()
  })

  it.each([
    ['updated', 'Ludusavi 清单已更新。'],
    ['invalid', '下载的清单无效。'],
  ] as const)('styles the %s result', async (status, message) => {
    const bridge = createMockBridge({
      update_ludusavi: async () => ok({ taskId: 'task-1' }),
      task_snapshot: async () => ok({
        id: 'task-1',
        kind: 'ludusavi_update',
        status: 'completed',
        progress: { completed: 1, total: 1 },
        message,
        result: { status, message, metadata: null },
        error: null,
      }),
    })
    const wrapper = mount(LudusaviSettings, { props: { bridge } })
    await flushPromises()

    await wrapper.get('[data-test="update-ludusavi"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="ludusavi-result"]').classes()).toContain(status)
    expect(wrapper.text()).toContain(message)
  })

  it('shows task stages while an update is running', async () => {
    vi.useFakeTimers()
    const taskSnapshot = vi
      .fn()
      .mockResolvedValueOnce(ok({
        id: 'task-1',
        kind: 'ludusavi_update',
        status: 'running',
        progress: { completed: 0, total: 1 },
        message: '正在验证下载的清单……',
        result: null,
        error: null,
      }))
      .mockResolvedValueOnce(ok({
        id: 'task-1',
        kind: 'ludusavi_update',
        status: 'completed',
        progress: { completed: 1, total: 1 },
        message: 'Ludusavi 清单已更新。',
        result: {
          status: 'updated',
          message: 'Ludusavi 清单已更新。',
          metadata: null,
        },
        error: null,
      }))
    const bridge = createMockBridge({
      update_ludusavi: async () => ok({ taskId: 'task-1' }),
      task_snapshot: taskSnapshot,
    })
    const wrapper = mount(LudusaviSettings, { props: { bridge } })
    await flushPromises()

    await wrapper.get('[data-test="update-ludusavi"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('正在验证下载的清单')
    expect(wrapper.get('[data-test="update-ludusavi"]').attributes('disabled')).toBeDefined()

    await vi.advanceTimersByTimeAsync(350)
    await flushPromises()
    expect(wrapper.text()).toContain('Ludusavi 清单已更新。')
  })
})
