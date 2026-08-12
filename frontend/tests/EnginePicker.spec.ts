import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMockBridge, fixtureGame, ok } from '../src/api/mockBridge'
import EnginePicker from '../src/features/engines/EnginePicker.vue'

describe('EnginePicker', () => {
  it('saves a known manual engine and emits the updated game', async () => {
    const updated = fixtureGame({ engineId: 'renpy', engineLabel: "Ren'Py", engineIsManual: true })
    const setGameEngine = vi.fn(async () => ok(updated))
    const bridge = createMockBridge({
      list_engine_options: async () => ok([
        { id: 'renpy', label: "Ren'Py", experimental: false },
        { id: 'unity', label: 'Unity', experimental: false },
      ]),
      set_game_engine: setGameEngine,
    })
    const wrapper = mount(EnginePicker, { props: { game: fixtureGame(), bridge } })
    await flushPromises()

    await wrapper.get('select').setValue('renpy')
    await wrapper.get('[data-test="save-engine"]').trigger('click')
    await flushPromises()

    expect(setGameEngine).toHaveBeenCalledWith({ gameId: 'game-1', engineId: 'renpy' })
    expect(wrapper.emitted('updated')?.[0]).toEqual([updated])
  })

  it('requires a label for a custom engine', async () => {
    const setGameEngine = vi.fn()
    const wrapper = mount(EnginePicker, {
      props: {
        game: fixtureGame(),
        bridge: createMockBridge({
          list_engine_options: async () => ok([]),
          set_game_engine: setGameEngine,
        }),
      },
    })
    await flushPromises()

    await wrapper.get('select').setValue('custom')
    await wrapper.get('[data-test="save-engine"]').trigger('click')

    expect(setGameEngine).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('请输入自定义引擎名称')
  })
})
