import { describe, expect, it } from 'vitest'
import '../src/styles/base.css'
import '../src/features/saves/batch-save.css'

describe('scrollbar theme', () => {
  it('defines the GameShelf dark scrollbar palette', () => {
    const root = getComputedStyle(document.documentElement)
    expect(root.getPropertyValue('--scrollbar-track').trim()).toBe('transparent')
    expect(root.getPropertyValue('--scrollbar-thumb').trim()).toBe('#4d4856')
    expect(root.getPropertyValue('--scrollbar-thumb-hover').trim()).toBe('#686173')
    expect(root.getPropertyValue('--scrollbar-thumb-active').trim()).toBe('#81778f')
  })

  it('applies a standards-based scrollbar fallback to scroll hosts', () => {
    const element = document.createElement('div')
    document.body.append(element)
    const style = getComputedStyle(element)
    expect(style.getPropertyValue('scrollbar-color')).not.toBe('')
    expect(style.getPropertyValue('scrollbar-width')).toBe('thin')
    element.remove()
  })

  it('uses the dark themed candidate result scroller', () => {
    const element = document.createElement('div')
    element.className = 'batch-save-results'
    document.body.append(element)
    const style = getComputedStyle(element)

    expect(style.overflowY).toBe('auto')
    expect(style.getPropertyValue('scrollbar-color')).toContain('var(--scrollbar-thumb)')
    expect(style.getPropertyValue('scrollbar-gutter')).toBe('stable')
    element.remove()
  })
})
