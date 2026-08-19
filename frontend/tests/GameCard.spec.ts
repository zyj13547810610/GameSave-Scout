import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { fixtureGame } from '../src/api/mockBridge'
import GameCard from '../src/features/library/GameCard.vue'

describe('GameCard', () => {
  it('allows a save-only card to be selected in batch mode', async () => {
    const wrapper = mount(GameCard, {
      props: {
        game: fixtureGame({ status: 'save_only' }),
        batchMode: true,
      },
    })

    expect(wrapper.get('button').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('button').classes()).not.toContain('batch-disabled')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('open')).toHaveLength(1)
  })
})
