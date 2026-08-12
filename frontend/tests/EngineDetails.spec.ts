import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import EngineDetails from '../src/features/engines/EngineDetails.vue'

describe('EngineDetails', () => {
  it('shows an adopted value and a different detected suggestion', async () => {
    const wrapper = mount(EngineDetails, {
      props: {
        adopted: { id: 'custom:Mine', label: 'Mine', variant: null, manual: true },
        detected: {
          id: 'unity',
          label: 'Unity',
          variant: null,
          confidence: '高',
          evidence: [{ code: 'unity_player', detail: '发现 UnityPlayer.dll', path: 'UnityPlayer.dll', weight: 0.42 }],
          ambiguous: false,
          experimental: false,
          alternatives: [],
        },
      },
    })

    expect(wrapper.text()).toContain('当前：Mine')
    expect(wrapper.text()).toContain('自动建议：Unity')
    expect(wrapper.text()).toContain('置信度：高')
    await wrapper.get('summary').trigger('click')
    expect(wrapper.text()).toContain('发现 UnityPlayer.dll')
  })

  it('labels ambiguous experimental suggestions', () => {
    const wrapper = mount(EngineDetails, {
      props: {
        adopted: { id: null, label: '未知引擎', variant: null, manual: false },
        detected: {
          id: null,
          label: '疑似多个引擎',
          variant: null,
          confidence: '中',
          evidence: [],
          ambiguous: true,
          experimental: true,
          alternatives: [{ id: 'qlie', label: 'QLIE' }],
        },
      },
    })

    expect(wrapper.text()).toContain('疑似')
    expect(wrapper.text()).toContain('实验性识别')
  })
})
