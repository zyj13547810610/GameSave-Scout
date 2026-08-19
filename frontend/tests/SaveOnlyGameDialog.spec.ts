import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMockBridge, fixtureGame, fixtureGroup, ok } from '../src/api/mockBridge'
import SaveOnlyGameDialog from '../src/features/saves/SaveOnlyGameDialog.vue'
import { fixtureBatchCandidate } from './batchSaveTestFixtures'

describe('SaveOnlyGameDialog', () => {
  it('requires a title and registry confirmation, then creates one grouped card', async () => {
    const create = vi.fn(async (input) => ok(fixtureGame({
      id: 'save-only-1', title: input.title, status: 'save_only', groupIds: input.groupIds,
    })))
    const wrapper = mount(SaveOnlyGameDialog, {
      props: {
        open: true, bridge: createMockBridge({ create_batch_save_only_game: create }),
        groups: [fixtureGroup()], candidates: [fixtureBatchCandidate({ kind: 'registry' })],
      },
    })
    await flushPromises()
    expect(wrapper.get('[data-test="create-save-only"]').attributes('disabled')).toBeDefined()

    await wrapper.get('[data-test="save-only-title"]').setValue('Alice Saves')
    await wrapper.get('[data-test="save-only-group-group-1"]').setValue(true)
    await wrapper.get('[data-test="save-only-confirm-registry"]').setValue(true)
    await wrapper.get('[data-test="save-only-form"]').trigger('submit')
    await flushPromises()

    expect(create).toHaveBeenCalledWith({
      title: 'Alice Saves', version: null, engineId: 'unity', groupIds: ['group-1'],
      candidateIds: ['candidate-1'], confirmRegistry: true,
    })
    expect(wrapper.emitted('created')?.[0][0]).toMatchObject({ status: 'save_only' })
  })
})
