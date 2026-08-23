import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { RuleTestResult } from '../src/api/contracts'
import RuleTestPanel from '../src/features/rules/RuleTestPanel.vue'

describe('RuleTestPanel', () => {
  it('does not allow testing until a local installed game is selected', async () => {
    const wrapper = mount(RuleTestPanel, {
      props: { games: [{ id: 'game-1', title: 'Alice', status: 'installed' }], result: null, busy: false, canMarkVerified: false },
    })
    expect(wrapper.get('[data-test="test-rule"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="rule-test-game"]').setValue('game-1')
    expect(wrapper.get('[data-test="test-rule"]').attributes('disabled')).toBeUndefined()
  })

  it('shows evidence and expanded locations and only marks a current verified result', () => {
    const result: RuleTestResult = {
      matched: true, summary: '命中 Unity', evidence: ['发现 UnityPlayer.dll'],
      expandedLocations: [{
        kind: 'directory', pathTemplate: '<winLocalAppDataLow>\\Studio\\Game',
        displayPath: 'C:\\Users\\Test\\AppData\\LocalLow\\Studio\\Game',
        exists: true, truncated: false, diagnostics: [],
      }],
      verificationToken: 'token-1',
    }
    const wrapper = mount(RuleTestPanel, {
      props: { games: [], result, busy: false, canMarkVerified: true },
    })
    expect(wrapper.text()).toContain('命中 Unity')
    expect(wrapper.text()).toContain('发现 UnityPlayer.dll')
    expect(wrapper.text()).toContain('LocalLow')
    expect(wrapper.get('[data-test="mark-rule-verified"]').attributes('disabled')).toBeUndefined()
  })
})
