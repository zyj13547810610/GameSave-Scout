import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { CoverCandidate } from '../src/api/contracts'
import CoverCandidateGallery from '../src/features/covers/CoverCandidateGallery.vue'

describe('CoverCandidateGallery', () => {
  it('labels used shared candidates and lazily decodes previews', () => {
    const wrapper = mount(CoverCandidateGallery, {
      props: {
        candidates: [candidate({
          shared: true,
          usedBy: [{ gameId: 'game-1', title: 'Alice' }],
        })],
        selectedId: null,
        gameTitle: 'Bob',
      },
    })

    expect(wrapper.text()).toContain('已用于：Alice')
    expect(wrapper.get('img').attributes('loading')).toBe('lazy')
    expect(wrapper.get('img').attributes('decoding')).toBe('async')
  })

  it('does not label an unused dedicated candidate', () => {
    const wrapper = mount(CoverCandidateGallery, {
      props: {
        candidates: [candidate()],
        selectedId: null,
        gameTitle: 'Alice',
      },
    })

    expect(wrapper.text()).not.toContain('已用于：')
  })
})

function candidate(overrides: Partial<CoverCandidate> = {}): CoverCandidate {
  return {
    id: 'candidate-1',
    gameId: 'game-2',
    source: 'cover_directory',
    sourceLabel: '导入目录',
    displayName: '86025945_p10.png',
    width: 600,
    height: 900,
    matchKind: 'fuzzy',
    score: 42,
    evidence: ['导入目录'],
    previewUrl: '/candidate.webp',
    vndbId: null,
    shared: false,
    usedBy: [],
    ...overrides,
  }
}
