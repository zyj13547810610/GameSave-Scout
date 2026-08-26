import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import CoverWizardQueue from '../src/features/covers/CoverWizardQueue.vue'
import '../src/features/library/library.css'

describe('CoverWizardQueue', () => {
  it('labels games that already had a cover in both queue layouts', () => {
    const wrapper = mount(CoverWizardQueue, {
      props: {
        items: [
          {
            gameId: 'game-1',
            title: 'Alice',
            version: null,
            initialHasCover: true,
            status: 'pending',
            candidateCount: 0,
            error: null,
          },
        ],
        selectedGameId: 'game-1',
        includeExisting: true,
      },
    })

    expect(wrapper.get('.cover-queue-existing-badge').text()).toBe('已有封面')
    expect(wrapper.get('.cover-queue-select option').text()).toContain('已有封面')
    wrapper.unmount()
  })

  it('sizes every queue row to its wrapped content', () => {
    const wrapper = mount(CoverWizardQueue, {
      props: {
        items: [
          {
            gameId: 'game-1',
            title: 'A very long game title that wraps onto multiple lines in the queue',
            version: 'v1.0.8',
            initialHasCover: false,
            status: 'pending',
            candidateCount: 0,
            error: null,
          },
          { gameId: 'game-2', title: 'Bob', version: null, initialHasCover: false, status: 'pending', candidateCount: 0, error: null },
        ],
        selectedGameId: 'game-1',
        includeExisting: false,
      },
    })

    const queueList = wrapper.get('[data-test="cover-queue-scroll"]')

    expect(getComputedStyle(queueList.element).gridAutoRows).toBe('max-content')
    expect(wrapper.get('.cover-queue-item-title').text()).not.toContain('v1.0.8')
    expect(wrapper.get('.cover-queue-version').text()).toBe('v1.0.8')
    expect(wrapper.get('.cover-queue-select option').text()).toContain('v1.0.8')
    wrapper.unmount()
  })

  it('keeps the selected queue item visible', async () => {
    const originalScrollIntoView = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      'scrollIntoView',
    )
    const scrollIntoView = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    })

    try {
      const wrapper = mount(CoverWizardQueue, {
        props: {
          items: [
            { gameId: 'game-1', title: 'Alice', version: null, initialHasCover: false, status: 'ready', candidateCount: 1, error: null },
            { gameId: 'game-2', title: 'Bob', version: null, initialHasCover: false, status: 'pending', candidateCount: 0, error: null },
          ],
          selectedGameId: 'game-1',
          includeExisting: false,
        },
      })

      await wrapper.setProps({ selectedGameId: 'game-2' })
      await nextTick()

      expect(scrollIntoView).toHaveBeenLastCalledWith({ block: 'nearest' })
      wrapper.unmount()
    } finally {
      if (originalScrollIntoView) {
        Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScrollIntoView)
      } else {
        delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView
      }
    }
  })
})
