import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CoverWizardSettings from '../src/features/covers/CoverWizardSettings.vue'
import type { CoverWizardSettings as Settings } from '../src/api/contracts'
import '../src/features/library/library.css'

const settings: Settings = {
  coverOnlineEnabled: false,
  coverVndbCandidateLimit: 5,
  coverLocalScanCandidateLimit: 10,
  coverOptimizeEnabled: true,
  coverLocalScanDepth: 2,
}

describe('CoverWizardSettings', () => {
  afterEach(() => vi.restoreAllMocks())

  it('sizes the popover from viewport space instead of the narrow trigger container', async () => {
    vi.spyOn(window, 'innerHeight', 'get').mockReturnValue(640)
    vi.spyOn(window, 'innerWidth', 'get').mockReturnValue(1180)
    const wrapper = mount(CoverWizardSettings, {
      attachTo: document.body,
      props: { settings },
    })
    const trigger = wrapper.get('[data-test="cover-settings-trigger"]')
    vi.spyOn(trigger.element, 'getBoundingClientRect').mockReturnValue({
      x: 140,
      y: 150,
      width: 80,
      height: 50,
      top: 150,
      right: 220,
      bottom: 200,
      left: 140,
      toJSON: () => ({}),
    } as DOMRect)

    await trigger.trigger('click')
    await flushPromises()

    const popover = wrapper.get('[data-test="cover-settings-popover"]')
    const style = getComputedStyle(popover.element)
    expect(style.position).toBe('fixed')
    expect(style.maxWidth).not.toBe('100%')
    expect((popover.element as HTMLElement).style.left).toBe('16px')
    expect((popover.element as HTMLElement).style.width).toBe('360px')
    expect((popover.element as HTMLElement).style.top).toBe('208px')
    expect((popover.element as HTMLElement).style.maxHeight).toBe('416px')
    expect(popover.classes()).toContain('placement-below')
    wrapper.unmount()
  })

  it('opens above the trigger when the remaining space below is too small', async () => {
    vi.spyOn(window, 'innerHeight', 'get').mockReturnValue(640)
    const wrapper = mount(CoverWizardSettings, {
      attachTo: document.body,
      props: { settings },
    })
    const trigger = wrapper.get('[data-test="cover-settings-trigger"]')
    vi.spyOn(trigger.element, 'getBoundingClientRect').mockReturnValue({
      x: 520,
      y: 500,
      width: 80,
      height: 50,
      top: 500,
      right: 600,
      bottom: 550,
      left: 520,
      toJSON: () => ({}),
    } as DOMRect)

    await trigger.trigger('click')
    await flushPromises()

    const popover = wrapper.get('[data-test="cover-settings-popover"]')
    expect(popover.classes()).toContain('placement-above')
    expect((popover.element as HTMLElement).style.maxHeight).toBe('448px')
    wrapper.unmount()
  })

  it('toggles an anchored dialog and preserves unsaved input across closing', async () => {
    const outside = document.createElement('button')
    document.body.appendChild(outside)
    const wrapper = mount(CoverWizardSettings, {
      attachTo: document.body,
      props: { settings },
    })

    const trigger = wrapper.get('[data-test="cover-settings-trigger"]')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    await trigger.trigger('click')
    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('[data-test="cover-settings-popover"]').attributes('role')).toBe('dialog')

    const online = wrapper.get('input[type="checkbox"]')
    await online.setValue(true)
    outside.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await flushPromises()
    expect(wrapper.find('[data-test="cover-settings-popover"]').exists()).toBe(false)

    await trigger.trigger('click')
    expect((wrapper.get('input[type="checkbox"]').element as HTMLInputElement).checked).toBe(true)
    await wrapper.get('form').trigger('keydown', { key: 'Escape' })
    await flushPromises()

    expect(wrapper.find('[data-test="cover-settings-popover"]').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
    wrapper.unmount()
    outside.remove()
  })

  it('keeps save failures visible and emits the unchanged settings DTO', async () => {
    const wrapper = mount(CoverWizardSettings, {
      props: { settings, error: '磁盘只读' },
    })
    await wrapper.get('[data-test="cover-settings-trigger"]').trigger('click')
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue(true)
    await inputs[1].setValue(7)
    await inputs[2].setValue(12)
    const optimize = wrapper.get('[data-test="cover-optimize-mode"]')
    const depth = wrapper.get('[data-test="cover-local-scan-depth"]')
    expect(wrapper.text()).toContain('自动优化（推荐，最长边 1920px）')
    expect(wrapper.text()).toContain('保留原尺寸与格式')
    expect(wrapper.text()).toContain('扫描游戏安装目录层数')
    expect(wrapper.text()).toContain('1 层（仅安装目录）')
    expect(wrapper.text()).toContain('2 层（安装目录和直接子目录，默认）')
    expect(wrapper.text()).toContain('3 层（再包含下一层子目录）')
    await optimize.setValue('preserve')
    await depth.setValue('3')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.get('[role="alert"]').text()).toBe('设置未保存：磁盘只读')
    expect(wrapper.emitted('save')).toEqual([[{
      coverOnlineEnabled: true,
      coverVndbCandidateLimit: 7,
      coverLocalScanCandidateLimit: 12,
      coverOptimizeEnabled: false,
      coverLocalScanDepth: 3,
    }]])
    wrapper.unmount()
  })
})
