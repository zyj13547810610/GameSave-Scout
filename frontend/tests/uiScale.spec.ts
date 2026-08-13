import { beforeEach, describe, expect, it } from 'vitest'
import {
  UI_SCALE_STORAGE_KEY,
  applyUiScale,
  getUiScaleStorage,
  readUiScale,
  saveUiScale,
} from '../src/features/preferences/uiScale'

describe('uiScale', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.style.removeProperty('--ui-scale')
  })

  it('defaults to 100% and rejects unsupported stored values', () => {
    expect(readUiScale(localStorage)).toBe(1)
    localStorage.setItem(UI_SCALE_STORAGE_KEY, '1.25')
    expect(readUiScale(localStorage)).toBe(1)
  })

  it('restores, applies, and saves an allowed scale', () => {
    localStorage.setItem(UI_SCALE_STORAGE_KEY, '1.2')
    const scale = readUiScale(localStorage)
    applyUiScale(scale, document.documentElement)
    saveUiScale(0.8, localStorage)

    expect(scale).toBe(1.2)
    expect(document.documentElement.style.getPropertyValue('--ui-scale')).toBe('1.2')
    expect(localStorage.getItem(UI_SCALE_STORAGE_KEY)).toBe('0.8')
  })

  it('migrates the legacy 130% scale to 120%', () => {
    localStorage.setItem(UI_SCALE_STORAGE_KEY, '1.3')

    expect(readUiScale(localStorage)).toBe(1.2)
    expect(localStorage.getItem(UI_SCALE_STORAGE_KEY)).toBe('1.2')
  })

  it('does not crash when the localStorage getter is blocked', () => {
    const blockedWindow = {} as Window
    Object.defineProperty(blockedWindow, 'localStorage', {
      get() { throw new DOMException('blocked', 'SecurityError') },
    })

    expect(getUiScaleStorage(blockedWindow)).toBeNull()
  })
})
