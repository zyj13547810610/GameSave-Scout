import type { InjectionKey } from 'vue'
import type { GameShelfBridge } from './contracts'
import { createMockBridge } from './mockBridge'

export const bridgeKey: InjectionKey<GameShelfBridge> = Symbol('GameShelfBridge')

type BridgeOptions = { windowObject?: Window }

export function createBridge(options: BridgeOptions = {}): GameShelfBridge {
  const windowObject = options.windowObject ?? window
  const available = windowObject.pywebview?.api
  if (available) return available
  if (options.windowObject || import.meta.env.DEV) return createMockBridge()
  return createDeferredBridge(windowObject)
}

function createDeferredBridge(windowObject: Window): GameShelfBridge {
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
