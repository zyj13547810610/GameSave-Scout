import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMockBridge, fixtureGame, ok } from '../src/api/mockBridge'
import BatchSaveAssociationDialog from '../src/features/saves/BatchSaveAssociationDialog.vue'

describe('BatchSaveAssociationDialog', () => {
  it('associates every selected candidate to one existing game', async () => {
    const reassociate = vi.fn(async () => ok({ updatedCount: 2 }))
    const wrapper = mount(BatchSaveAssociationDialog, {
      props: {
        open: true, bridge: createMockBridge({ reassociate_batch_save_candidates: reassociate }),
        games: [fixtureGame()], candidateIds: ['candidate-1', 'candidate-2'],
      },
    })
    await wrapper.get('[data-test="association-game"]').setValue('game-1')
    await wrapper.get('[data-test="association-form"]').trigger('submit')
    await flushPromises()

    expect(reassociate).toHaveBeenCalledWith({
      candidateIds: ['candidate-1', 'candidate-2'], gameId: 'game-1',
    })
    expect(wrapper.emitted('applied')).toEqual([[2]])
  })

  it('keeps the dialog and selection after a service failure', async () => {
    const wrapper = mount(BatchSaveAssociationDialog, {
      props: {
        open: true, games: [fixtureGame()], candidateIds: ['candidate-1'],
        bridge: createMockBridge({
          async reassociate_batch_save_candidates() {
            return { ok: false, error: { code: 'stale', message: '候选已变化' } }
          },
        }),
      },
    })
    await wrapper.get('[data-test="association-game"]').setValue('game-1')
    await wrapper.get('[data-test="association-form"]').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[data-test="association-dialog"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('候选已变化')
  })
})
