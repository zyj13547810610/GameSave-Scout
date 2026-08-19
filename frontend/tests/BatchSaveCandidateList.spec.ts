import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMockBridge, fixtureGame, ok } from '../src/api/mockBridge'
import BatchSaveCandidateList from '../src/features/saves/BatchSaveCandidateList.vue'
import { fixtureBatchCandidate } from './batchSaveTestFixtures'

describe('BatchSaveCandidateList', () => {
  it('shows evidence and sends only candidate identity for explicit lookup', async () => {
    const lookup = vi.fn(async () => ok({ opened: true, url: 'https://vndb.org/v?q=Alice' }))
    const candidate = fixtureBatchCandidate({
      confidence: 'medium', suggestedGameId: null, classification: 'unknown',
      alternatives: [{ title: 'Alice 2', reason: '标题相近', gameId: null }],
    })
    const wrapper = mount(BatchSaveCandidateList, {
      props: {
        bridge: createMockBridge({ open_batch_save_lookup: lookup }),
        candidates: [candidate], games: [fixtureGame()], selectedIds: new Set<string>(),
      },
    })

    expect(wrapper.text()).toContain(candidate.displayPath)
    expect(wrapper.text()).toContain('slot1.sav')
    expect(wrapper.text()).toContain('Alice 2')
    expect(lookup).not.toHaveBeenCalled()

    await wrapper.get('[data-test="lookup-vndb-candidate-1"]').trigger('click')
    await flushPromises()
    expect(lookup).toHaveBeenCalledWith({ candidateId: 'candidate-1', provider: 'vndb' })
  })

  it('does not preselect high-confidence candidates and marks only a suggested target', () => {
    const wrapper = mount(BatchSaveCandidateList, {
      props: {
        bridge: createMockBridge(), candidates: [fixtureBatchCandidate()],
        games: [fixtureGame()], selectedIds: new Set<string>(),
      },
    })

    expect((wrapper.get('[data-test="select-candidate-1"]').element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.text()).toContain('建议目标')
  })
})
