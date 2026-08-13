export const UI_SCALE_OPTIONS = [0.8, 0.9, 1, 1.1, 1.2] as const
export type UiScale = (typeof UI_SCALE_OPTIONS)[number]
export const UI_SCALE_STORAGE_KEY = 'gameshelf.ui-scale'
const LEGACY_MAX_UI_SCALE = 1.3

export function isUiScale(value: number): value is UiScale {
  return UI_SCALE_OPTIONS.some((option) => option === value)
}

export function getUiScaleStorage(windowObject: Pick<Window, 'localStorage'>): Storage | null {
  try {
    return windowObject.localStorage
  } catch {
    return null
  }
}

export function readUiScale(
  storage: Pick<Storage, 'getItem' | 'setItem'> | null,
): UiScale {
  try {
    const value = Number(storage?.getItem(UI_SCALE_STORAGE_KEY))
    if (value === LEGACY_MAX_UI_SCALE) {
      try {
        storage?.setItem(UI_SCALE_STORAGE_KEY, '1.2')
      } catch {
        // 迁移写回失败时仍在本次运行中使用新的最大档位。
      }
      return 1.2
    }
    return isUiScale(value) ? value : 1
  } catch {
    return 1
  }
}

export function applyUiScale(scale: UiScale, root: HTMLElement): void {
  root.style.setProperty('--ui-scale', String(scale))
}

export function saveUiScale(scale: UiScale, storage: Pick<Storage, 'setItem'> | null): void {
  try {
    storage?.setItem(UI_SCALE_STORAGE_KEY, String(scale))
  } catch {
    // 存储不可用时仍保留本次运行中的缩放效果。
  }
}
