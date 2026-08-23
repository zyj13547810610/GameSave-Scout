import type { InjectionKey } from 'vue'
import type { GameShelfBridge } from './contracts'
import { createMockBridge } from './mockBridge'

export const bridgeKey: InjectionKey<GameShelfBridge> = Symbol('GameShelfBridge')

type BridgeOptions = { windowObject?: Window }

export const ruleBridgeMethods = [
  'list_rules',
  'get_rule',
  'validate_rule_draft',
  'test_rule_draft',
  'save_rule',
  'copy_rule',
  'set_rule_enabled',
  'delete_rule',
  'refresh_rules',
  'get_game_save_rule_prefill',
  'begin_rule_import',
  'confirm_rule_import',
  'export_rule',
  'open_rule_directory',
  'restore_bundled_ludusavi',
] as const satisfies readonly (keyof GameShelfBridge)[]

export function createBridge(options: BridgeOptions = {}): GameShelfBridge {
  const windowObject = options.windowObject ?? window
  const available = windowObject.pywebview?.api
  if (available) return available
  if (options.windowObject || import.meta.env.DEV) return createMockBridge()
  return createDeferredBridge(windowObject)
}

export function createDeferredBridge(windowObject: Window): GameShelfBridge {
  let apiPromise: Promise<GameShelfBridge> | undefined
  const api = () => (apiPromise ??= waitForPywebview(windowObject))
  return new Proxy({} as GameShelfBridge, {
    get(_target, property: keyof GameShelfBridge) {
      return async (...args: unknown[]) => {
        const target = await api()
        const method = target[property] as (...values: unknown[]) => unknown
        return method.apply(target, args)
      }
    },
  })
}

function waitForPywebview(windowObject: Window): Promise<GameShelfBridge> {
  if (windowObject.pywebview?.api) return Promise.resolve(windowObject.pywebview.api)
  return new Promise((resolve) => {
    windowObject.addEventListener('pywebviewready', () => resolve(windowObject.pywebview!.api), { once: true })
  })
}
