import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { CoverWizardSettings } from '../src/api/contracts'
import { createMockBridge } from '../src/api/mockBridge'
import CoverActions from '../src/features/covers/CoverActions.vue'
import { readClipboardPng } from '../src/features/covers/coverClipboard'

const settings: CoverWizardSettings = {
  coverOnlineEnabled: true,
  coverVndbCandidateLimit: 7,
  coverLocalScanCandidateLimit: 12,
  coverOptimizeEnabled: true,
  coverLocalScanDepth: 3,
}

describe('cover clipboard', () => {
  it('selects the first PNG clipboard item and returns raw base64', async () => {
    const clipboard = fakeClipboard('image/png', new Uint8Array([137, 80, 78, 71]))

    const base64 = await readClipboardPng(clipboard)

    expect(base64).toBe('iVBORw==')
  })

  it('shows a useful message when the clipboard has no image', async () => {
    const wrapper = mount(CoverActions, {
      props: { gameId: 'game-1', hasCover: false, bridge: createMockBridge(), settings },
      global: { provide: { clipboard: fakeClipboard('text/plain', new Uint8Array([1])) } },
    })

    await wrapper.get('[data-test="paste-cover"]').trigger('click')

    expect(wrapper.text()).toContain('剪贴板中没有可用图片')
  })

  it('updates only the shared cover optimization setting with an explicit select', async () => {
    const save = vi.fn(async (input: CoverWizardSettings) => ({ ok: true as const, data: input }))
    const wrapper = mount(CoverActions, {
      props: {
        gameId: 'game-1',
        hasCover: false,
        bridge: createMockBridge({ set_cover_wizard_settings: save }),
        settings,
      },
    })

    expect(wrapper.text()).toContain('封面保存方式')
    expect(wrapper.text()).toContain('自动优化（推荐，最长边 1920px）')
    expect(wrapper.text()).toContain('保留原尺寸与格式')
    await wrapper.get('[data-test="detail-cover-optimize-mode"]').setValue('preserve')

    expect(save).toHaveBeenCalledWith({ ...settings, coverOptimizeEnabled: false })
    expect(wrapper.emitted('settingsUpdated')).toEqual([[
      { ...settings, coverOptimizeEnabled: false },
    ]])
  })

  it('keeps the selected save mode and shows an inline error when saving fails', async () => {
    const wrapper = mount(CoverActions, {
      props: {
        gameId: 'game-1',
        hasCover: false,
        bridge: createMockBridge({
          async set_cover_wizard_settings() {
            return { ok: false, error: { code: 'config_save_failed', message: '磁盘只读' } }
          },
        }),
        settings,
      },
    })

    const select = wrapper.get('[data-test="detail-cover-optimize-mode"]')
    await select.setValue('preserve')

    expect((select.element as HTMLSelectElement).value).toBe('preserve')
    expect(wrapper.text()).toContain('设置未保存：磁盘只读')
    expect(wrapper.emitted('settingsUpdated')).toBeUndefined()
  })
})

function fakeClipboard(type: string, bytes: Uint8Array): Clipboard {
  return {
    async read() {
      return [{
        types: [type],
        presentationStyle: 'unspecified',
        async getType() { return new Blob([bytes.slice().buffer as ArrayBuffer], { type }) },
      } as unknown as ClipboardItem]
    },
  } as Clipboard
}
