import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMockBridge, ok } from '../src/api/mockBridge'
import LudusaviSettings from '../src/features/saves/LudusaviSettings.vue'

enableAutoUnmount(afterEach)

describe('LudusaviSettings', () => {
  it('shows fixed snapshot metadata and only updates after an explicit click', async () => {
    const update = vi.fn(async () => ok({ taskId: 'task-1' }))
    const bridge = createMockBridge({
      ludusavi_status: async () => ok({
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
  })
})
