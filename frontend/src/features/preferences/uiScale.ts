export const UI_SCALE_OPTIONS = [0.8, 0.9, 1, 1.1, 1.2] as const
export type UiScale = (typeof UI_SCALE_OPTIONS)[number]

export function isUiScale(value: number): value is UiScale {
  return UI_SCALE_OPTIONS.some((option) => option === value)
}

export function applyUiScale(scale: UiScale, root: HTMLElement): void {
  root.style.setProperty('--ui-scale', String(scale))
}
