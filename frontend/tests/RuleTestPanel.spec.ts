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

  it('filters installed games by title and clears a selection hidden by the filter', async () => {
    const wrapper = mount(RuleTestPanel, {
      props: {
        games: [
          { id: 'game-1', title: 'Summer Pockets', status: 'installed' },
          { id: 'game-2', title: '千恋＊万花', status: 'installed' },
          { id: 'game-3', title: 'Missing Game', status: 'missing' },
        ],
        result: null,
        busy: false,
        canMarkVerified: false,
      },
    })

    await wrapper.get('[data-test="rule-test-game"]').setValue('game-1')
    await wrapper.get('[data-test="rule-test-game-filter"]').setValue('千恋')

    const options = wrapper.findAll('[data-test="rule-test-game"] option')
    expect(options.map((option) => option.text())).toEqual(['请选择已安装游戏', '千恋＊万花'])
    expect(wrapper.get('[data-test="rule-test-game"]').element).toHaveProperty('value', '')
    expect(wrapper.get('[data-test="test-rule"]').attributes('disabled')).toBeDefined()
  })

  it('matches installed game titles case-insensitively and shows an empty result', async () => {
    const wrapper = mount(RuleTestPanel, {
      props: {
        games: [{ id: 'game-1', title: 'Summer Pockets', status: 'installed' }],
        result: null,
        busy: false,
        canMarkVerified: false,
      },
    })

    await wrapper.get('[data-test="rule-test-game-filter"]').setValue('SUMMER')
    expect(wrapper.findAll('[data-test="rule-test-game"] option').map((option) => option.text()))
      .toEqual(['请选择已安装游戏', 'Summer Pockets'])

    await wrapper.get('[data-test="rule-test-game-filter"]').setValue('不存在')
    expect(wrapper.findAll('[data-test="rule-test-game"] option').map((option) => option.text()))
      .toEqual(['没有匹配的已安装游戏'])
  })
})
