import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMockBridge, fixtureRoot, ok } from '../src/api/mockBridge'
import ScanRootDialog from '../src/features/scan-roots/ScanRootDialog.vue'

describe('ScanRootDialog', () => {
  it('uses removable Mods defaults only for a new root', async () => {
    const addRoot = vi.fn(async (input) => ok(fixtureRoot({ exclusions: input.exclusions })))
    const wrapper = mount(ScanRootDialog, {
      props: { bridge: createMockBridge({ add_root: addRoot }) },
    })

    expect(wrapper.get('[data-test="root-exclusions"]').element).toMatchObject({
      value: 'Mods\n**/Mods',
    })
    await wrapper.get('[data-test="root-exclusions"]').setValue('')
    await wrapper.get('[data-test="display-path"]').setValue('D:\\Games')
    await wrapper.get('form').trigger('submit')

    expect(addRoot).toHaveBeenCalledWith({
      displayPath: 'D:\\Games',
      scanMode: 'children',
      maxDepth: 1,
      exclusions: [],
    })
    expect(wrapper.emitted('saved')?.[0]?.[1]).toBe(true)
  })

  it('does not add defaults when an existing root has no exclusions', () => {
    const wrapper = mount(ScanRootDialog, {
      props: { bridge: createMockBridge(), root: fixtureRoot({ exclusions: [] }) },
    })

    expect(wrapper.get('[data-test="root-exclusions"]').element).toMatchObject({ value: '' })
  })

  it('validates recursive depth before calling the bridge', async () => {
    const bridge = createMockBridge()
    const addRoot = vi.spyOn(bridge, 'add_root')
    const wrapper = mount(ScanRootDialog, { props: { bridge } })
    await wrapper.get('[data-test="display-path"]').setValue('D:\\Games')
    await wrapper.get('[data-test="mode-recursive"]').setValue(true)
    await wrapper.get('[data-test="max-depth"]').setValue(9)
    await wrapper.get('form').trigger('submit')

    expect(wrapper.text()).toContain('扫描深度必须在 1 到 8 之间')
    expect(addRoot).not.toHaveBeenCalled()
  })

  it('prefills and updates an existing root', async () => {
    const root = fixtureRoot({
      enabled: false,
      scanMode: 'recursive',
      maxDepth: 4,
      exclusions: ['Tools', '**/Cache'],
    })
    const updateRoot = vi.fn(async () => ok(root))
    const bridge = createMockBridge({ update_root: updateRoot })
    const wrapper = mount(ScanRootDialog, { props: { bridge, root } })

    expect(wrapper.get('[data-test="mode-recursive"]').element).toMatchObject({ checked: true })
    expect(wrapper.get('[data-test="max-depth"]').element).toMatchObject({ value: '4' })
    expect(wrapper.get('[data-test="root-exclusions"]').element).toMatchObject({ value: 'Tools\n**/Cache' })
    await wrapper.get('[data-test="root-exclusions"]').setValue('Tools\nGameA')
    await wrapper.get('form').trigger('submit')

    expect(updateRoot).toHaveBeenCalledWith({
      rootId: root.id,
      displayPath: root.displayPath,
      enabled: false,
      scanMode: 'recursive',
      maxDepth: 4,
      exclusions: ['Tools', 'GameA'],
    })
    expect(wrapper.emitted('saved')).toEqual([[root, false]])
  })
})
