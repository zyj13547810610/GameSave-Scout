import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CoverWizardSettings from '../src/features/covers/CoverWizardSettings.vue'
import type { CoverWizardSettings as Settings } from '../src/api/contracts'

const settings: Settings = {
  coverOnlineEnabled: false,
  coverVndbCandidateLimit: 5,
  coverLocalScanCandidateLimit: 10,
}

describe('CoverWizardSettings', () => {
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
    await wrapper.get('form').trigger('submit')

    expect(wrapper.get('[role="alert"]').text()).toBe('设置未保存：磁盘只读')
    expect(wrapper.emitted('save')).toEqual([[{
      coverOnlineEnabled: true,
      coverVndbCandidateLimit: 7,
      coverLocalScanCandidateLimit: 12,
    }]])
    wrapper.unmount()
  })
})
