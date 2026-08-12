import { enableAutoUnmount, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { createMockBridge, fixtureGame } from '../src/api/mockBridge'
import GameDetailDrawer from '../src/features/library/GameDetailDrawer.vue'

enableAutoUnmount(afterEach)

afterEach(() => {
  document.documentElement.classList.remove('detail-open')
  document.body.innerHTML = ''
})

describe('GameDetailDrawer', () => {
  it('uses the full original cover', () => {
    const wrapper = mount(GameDetailDrawer, {
      props: {
        game: fixtureGame({ coverOriginalUrl: '/cover/original' }),
        bridge: createMockBridge(),
      },
      attachTo: document.body,
    })

    expect(wrapper.get('[data-test="detail-cover"]').attributes('src')).toBe('/cover/original')
  })

  it('shows only one visible close button', () => {
    const wrapper = mount(GameDetailDrawer, {
      props: { game: fixtureGame(), bridge: createMockBridge() },
      attachTo: document.body,
    })

    const closeButtons = wrapper.findAll('button').filter((button) => button.text() === '×')
    expect(closeButtons).toHaveLength(1)
  })

  it('closes from the backdrop', async () => {
    const wrapper = mount(GameDetailDrawer, {
      props: { game: fixtureGame(), bridge: createMockBridge() },
      attachTo: document.body,
    })

    await wrapper.get('[data-test="drawer-backdrop"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('locks page scrolling and always cleans the lock', () => {
    const wrapper = mount(GameDetailDrawer, {
      props: { game: fixtureGame(), bridge: createMockBridge() },
      attachTo: document.body,
    })

    expect(document.documentElement.classList.contains('detail-open')).toBe(true)
    wrapper.unmount()
    expect(document.documentElement.classList.contains('detail-open')).toBe(false)
  })

  it('closes on Escape from anywhere in the window', () => {
    const wrapper = mount(GameDetailDrawer, {
      props: { game: fixtureGame(), bridge: createMockBridge() },
      attachTo: document.body,
    })

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('keeps keyboard focus inside the modal drawer', () => {
    const outside = document.createElement('button')
    document.body.append(outside)
    const wrapper = mount(GameDetailDrawer, {
      props: { game: fixtureGame(), bridge: createMockBridge() },
      attachTo: document.body,
    })
    outside.focus()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', cancelable: true }))

    expect(document.activeElement).toBe(wrapper.get('[data-test="drawer-close"]').element)
  })
})
