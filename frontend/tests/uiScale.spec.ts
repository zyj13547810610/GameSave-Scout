import { beforeEach, describe, expect, it } from 'vitest'
import { applyUiScale, isUiScale } from '../src/features/preferences/uiScale'
import '../src/features/rules/rules.css'

describe('uiScale', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.style.removeProperty('--ui-scale')
  })

  it('accepts only the five supported scale values', () => {
    expect([0.8, 0.9, 1, 1.1, 1.2].every(isUiScale)).toBe(true)
    expect(isUiScale(1.25)).toBe(false)
  })

  it('applies an allowed scale to the document root', () => {
    applyUiScale(1.2, document.documentElement)
    expect(document.documentElement.style.getPropertyValue('--ui-scale')).toBe('1.2')
  })

  it('keeps the rule workspace responsive at the five-scale upper bound', () => {
    const responsiveRule = Array.from(document.styleSheets)
      .flatMap((sheet) => Array.from(sheet.cssRules))
      .find((rule) => rule.cssText.startsWith('@container (max-width: 60rem)'))
    expect(responsiveRule).toBeDefined()
  })
})
