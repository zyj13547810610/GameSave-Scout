import { enableAutoUnmount, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { createMockBridge, fixtureGame } from '../src/api/mockBridge'
import EngineSection from '../src/features/engines/EngineSection.vue'

enableAutoUnmount(afterEach)

describe('EngineSection', () => {
  it('is closed by default and summarizes the current automatic engine', () => {
    const wrapper = mount(EngineSection, {
      props: {
        game: fixtureGame({
          engineId: 'unity',
          engineLabel: 'Unity',
          engineIsManual: false,
          detectedEngine: {
            id: 'unity',
            label: 'Unity',
            variant: null,
            confidence: '高',
            evidence: [],
            ambiguous: false,
            experimental: false,
            alternatives: [],
          },
        }),
        bridge: createMockBridge(),
      },
    })

    const section = wrapper.get('[data-test="engine-section"]')
    expect((section.element as HTMLDetailsElement).open).toBe(false)
    expect(section.get('summary').text()).toContain('Unity')
    expect(section.get('summary').text()).toContain('自动识别')
    expect(section.get('summary').text()).toContain('高可信度')
  })

  it('marks unknown and ambiguous results as warnings', () => {
    const unknown = mount(EngineSection, {
      props: { game: fixtureGame(), bridge: createMockBridge() },
    })
    const ambiguous = mount(EngineSection, {
      props: {
        game: fixtureGame({
          detectedEngine: {
            id: null,
            label: '疑似多个引擎',
            variant: null,
            confidence: '中',
            evidence: [],
            ambiguous: true,
            experimental: false,
            alternatives: [],
          },
        }),
        bridge: createMockBridge(),
      },
    })

    expect(unknown.get('summary').classes()).toContain('warning')
    expect(ambiguous.get('summary').classes()).toContain('warning')
  })
})
