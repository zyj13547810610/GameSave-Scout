import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMockBridge } from '../src/api/mockBridge'
import CoverActions from '../src/features/covers/CoverActions.vue'
import { readClipboardPng } from '../src/features/covers/coverClipboard'

describe('cover clipboard', () => {
  it('selects the first PNG clipboard item and returns raw base64', async () => {
    const clipboard = fakeClipboard('image/png', new Uint8Array([137, 80, 78, 71]))

    const base64 = await readClipboardPng(clipboard)

    expect(base64).toBe('iVBORw==')
  })

  it('shows a useful message when the clipboard has no image', async () => {
    const wrapper = mount(CoverActions, {
      props: { gameId: 'game-1', hasCover: false, bridge: createMockBridge() },
      global: { provide: { clipboard: fakeClipboard('text/plain', new Uint8Array([1])) } },
    })

    await wrapper.get('[data-test="paste-cover"]').trigger('click')

    expect(wrapper.text()).toContain('剪贴板中没有可用图片')
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
