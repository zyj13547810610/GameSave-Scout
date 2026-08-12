export const UI_SCALE_OPTIONS = [0.9, 1, 1.1, 1.2, 1.3] as const
export type UiScale = (typeof UI_SCALE_OPTIONS)[number]
export const UI_SCALE_STORAGE_KEY = 'gameshelf.ui-scale'

function isUiScale(value: number): value is UiScale {
  return UI_SCALE_OPTIONS.some((option) => option === value)
}

export function readUiScale(storage: Storage): UiScale {
  try {
    const value = Number(storage.getItem(UI_SCALE_STORAGE_KEY))
    return isUiScale(value) ? value : 1
  } catch {
    return 1
  }
}

export function applyUiScale(scale: UiScale, root: HTMLElement): void {
  root.style.setProperty('--ui-scale', String(scale))
}

export function saveUiScale(scale: UiScale, storage: Storage): void {
  try {
    storage.setItem(UI_SCALE_STORAGE_KEY, String(scale))
  } catch {
    // 存储不可用时仍保留本次运行中的缩放效果。
  }
}
