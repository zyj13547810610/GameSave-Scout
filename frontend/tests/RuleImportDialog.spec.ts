import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { RuleImportPreview } from '../src/api/contracts'
import RuleImportDialog from '../src/features/rules/RuleImportDialog.vue'

function preview(): RuleImportPreview {
  return {
    cancelled: false,
    sessionId: 'session-1',
    items: [
      {
        itemId: 'fresh', fileName: 'fresh.yaml', valid: true, errors: [],
        qualifiedId: 'user:fresh', ruleType: 'engine', status: 'experimental',
        conflict: 'none', allowedDecisions: ['import', 'skip'],
      },
      {
        itemId: 'builtin', fileName: 'builtin.yaml', valid: true, errors: [],
        qualifiedId: 'user:kiri', ruleType: 'engine', status: 'experimental',
        conflict: 'builtin', allowedDecisions: ['new_id', 'skip'],
      },
      {
        itemId: 'broken', fileName: 'broken.yaml', valid: false, errors: ['格式错误'],
        qualifiedId: null, ruleType: null, status: null,
        conflict: 'invalid', allowedDecisions: ['skip'],
      },
    ],
  }
}

describe('RuleImportDialog', () => {
  it('only offers backend allowed decisions and waits for every conflict decision', async () => {
    const wrapper = mount(RuleImportDialog, {
      props: { preview: preview(), busy: false, error: '' },
    })
    const builtin = wrapper.get('[data-test="import-decision-builtin"]')
    expect(builtin.findAll('option').map((item) => item.attributes('value'))).toEqual(['', 'new_id', 'skip'])
    expect(builtin.text()).not.toContain('替换')
    expect(wrapper.get('[data-test="confirm-rule-import"]').attributes('disabled')).toBeDefined()

    await builtin.setValue('new_id')
    await wrapper.get('[data-test="import-new-id-builtin"]').setValue('kiri_custom')
    expect(wrapper.get('[data-test="confirm-rule-import"]').attributes('disabled')).toBeUndefined()
  })

  it('keeps the preview visible with an explicit batch error', () => {
    const wrapper = mount(RuleImportDialog, {
      props: { preview: preview(), busy: false, error: '整批导入失败，未写入文件。' },
    })
    expect(wrapper.text()).toContain('fresh.yaml')
    expect(wrapper.text()).toContain('整批导入失败')
  })
})
