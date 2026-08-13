import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import UiScaleControl from '../src/features/preferences/UiScaleControl.vue'

describe('UiScaleControl', () => {
  it('shows all five levels and emits a numeric scale', async () => {
    const wrapper = mount(UiScaleControl, { props: { modelValue: 1 } })
    const options = wrapper.findAll('option').map((option) => option.text())
    expect(options).toEqual(['80%', '90%', '100%', '110%', '120%'])

    await wrapper.get('[data-test="ui-scale"]').setValue('1.2')
    expect(wrapper.emitted('update:modelValue')).toEqual([[1.2]])
  })

  it('does not emit unsupported values', async () => {
    const wrapper = mount(UiScaleControl, { props: { modelValue: 1 } })
    const select = wrapper.get('[data-test="ui-scale"]')
    const unsupported = document.createElement('option')
    unsupported.value = '1.25'
    unsupported.textContent = '125%'
    select.element.append(unsupported)

    await select.setValue('1.25')

    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })
})
