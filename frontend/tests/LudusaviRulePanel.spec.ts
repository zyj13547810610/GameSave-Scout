import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMockBridge, ok } from '../src/api/mockBridge'
import LudusaviRulePanel from '../src/features/rules/LudusaviRulePanel.vue'

enableAutoUnmount(afterEach)
afterEach(() => vi.useRealTimers())

function bundledStatus() {
  return {
    available: true as const,
    source: 'bundled' as const,
    bundledSha256: '1234567890abcdef'.repeat(4),
    unavailableReason: null,
    sourceUrl: 'https://example.test/manifest.yaml',
    downloadedAt: '2026-08-12T00:00:00+00:00',
    sha256: '1234567890abcdef'.repeat(4),
    etag: '"etag"',
    upstreamCommit: 'abc123',
  }
}

describe('LudusaviRulePanel', () => {
  it('shows the local bundled source and metadata without starting an update', async () => {
    const update = vi.fn(async () => ok({ taskId: 'task-1' }))
    const wrapper = mount(LudusaviRulePanel, {
      props: { bridge: createMockBridge({ ludusavi_status: async () => ok(bundledStatus()), update_ludusavi: update }) },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('随包版本')
    expect(wrapper.text()).toContain('1234567890ab')
    expect(wrapper.text()).toContain('abc123')
    expect(update).not.toHaveBeenCalled()
  })

  it('labels an active user snapshot and preserves it after update failure', async () => {
    const active = { ...bundledStatus(), source: 'active' as const, sha256: 'abcdef1234567890'.repeat(4) }
    const bridge = createMockBridge({
      ludusavi_status: async () => ok(active),
      update_ludusavi: async () => ok({ taskId: 'task-1' }),
      task_snapshot: async () => ok({
        id: 'task-1', kind: 'ludusavi_update', status: 'completed',
        progress: { completed: 1, total: 1 }, message: '网络失败，当前版本保持不变。',
        result: { status: 'failed', message: '网络失败，当前版本保持不变。', metadata: null }, error: null,
      }),
    })
    const wrapper = mount(LudusaviRulePanel, { props: { bridge } })
    await flushPromises()
    await wrapper.get('[data-test="update-ludusavi"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('用户更新版本')
    expect(wrapper.text()).toContain('abcdef123456')
    expect(wrapper.text()).toContain('当前版本保持不变')
  })

  it('shows unavailable reason while keeping explicit recovery actions', async () => {
    const wrapper = mount(LudusaviRulePanel, {
      props: { bridge: createMockBridge({
        ludusavi_status: async () => ok({
          available: false, source: null, bundledSha256: null,
          unavailableReason: '随包与用户快照均损坏', sourceUrl: null,
          downloadedAt: null, sha256: null, etag: null, upstreamCommit: null,
        }),
      }) },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('不可用')
    expect(wrapper.text()).toContain('随包与用户快照均损坏')
    expect(wrapper.get('[data-test="update-ludusavi"]').attributes('disabled')).toBeUndefined()
  })

  it('confirms restore, preserves status on failure, and opens only the user rule directory', async () => {
    const restore = vi.fn()
      .mockResolvedValueOnce({ ok: false, error: { code: 'restore_failed', message: '恢复失败，活动版本保持不变' } })
      .mockResolvedValueOnce(ok(bundledStatus()))
    const openDirectory = vi.fn(async () => ok({ opened: true }))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValue(true)
    const wrapper = mount(LudusaviRulePanel, {
      props: { bridge: createMockBridge({
        ludusavi_status: async () => ok({ ...bundledStatus(), source: 'active' as const }),
        restore_bundled_ludusavi: restore,
        open_rule_directory: openDirectory,
      }) },
    })
    await flushPromises()

    await wrapper.get('[data-test="restore-bundled-ludusavi"]').trigger('click')
    expect(restore).not.toHaveBeenCalled()
    await wrapper.get('[data-test="restore-bundled-ludusavi"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('用户更新版本')
    expect(wrapper.text()).toContain('活动版本保持不变')
    await wrapper.get('[data-test="restore-bundled-ludusavi"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('随包版本')

    await wrapper.get('[data-test="open-rule-directory"]').trigger('click')
    expect(openDirectory).toHaveBeenCalledWith({ target: 'user' })
    confirm.mockRestore()
  })

  it('shows the probing stage reported by the existing background task', async () => {
    vi.useFakeTimers()
    const snapshots = vi.fn()
      .mockResolvedValueOnce(ok({
        id: 'task-1', kind: 'ludusavi_update', status: 'running',
        progress: { completed: 0, total: 1 }, message: '正在冷查询探测新索引……', result: null, error: null,
      }))
      .mockResolvedValueOnce(ok({
        id: 'task-1', kind: 'ludusavi_update', status: 'completed',
        progress: { completed: 1, total: 1 }, message: 'Ludusavi 规则已是最新。',
        result: { status: 'not_modified', message: 'Ludusavi 规则已是最新。', metadata: null }, error: null,
      }))
    const wrapper = mount(LudusaviRulePanel, {
      props: { bridge: createMockBridge({
        update_ludusavi: async () => ok({ taskId: 'task-1' }),
        task_snapshot: snapshots,
      }) },
    })
    await flushPromises()
    await wrapper.get('[data-test="update-ludusavi"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('冷查询探测新索引')
    await vi.advanceTimersByTimeAsync(350)
    await flushPromises()
    expect(wrapper.text()).toContain('已是最新')
  })
})
