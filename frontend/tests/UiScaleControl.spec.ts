import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import UiScaleControl from '../src/features/preferences/UiScaleControl.vue'

describe('UiScaleControl', () => {
  it('shows all five levels and emits a numeric scale', async () => {
    const wrapper = mount(UiScaleControl, { props: { modelValue: 1 } })
    const options = wrapper.findAll('option').map((option) => option.text())
    expect(options).toEqual(['90%', '100%', '110%', '120%', '130%'])

    await wrapper.get('[data-test="ui-scale"]').setValue('1.2')
    expect(wrapper.emitted('update:modelValue')).toEqual([[1.2]])
  })
})
