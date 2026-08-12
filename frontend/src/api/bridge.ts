import type { GameShelfBridge } from './contracts'
import { createMockBridge } from './mockBridge'

type BridgeOptions = {
  windowObject?: Window
}

export function createBridge(options: BridgeOptions = {}): GameShelfBridge {
  const windowObject = options.windowObject ?? window
  const available = windowObject.pywebview?.api
  if (available) return available
  if (options.windowObject || import.meta.env.DEV) return createMockBridge()
  return createDeferredBridge(windowObject)
}

function createDeferredBridge(windowObject: Window): GameShelfBridge {
  let apiPromise: Promise<GameShelfBridge> | undefined
  const api = () => {
    apiPromise ??= waitForPywebview(windowObject)
    return apiPromise
  }
  return {
    async bootstrap() {
      return (await api()).bootstrap()
    },
    async task_snapshot(taskId) {
      return (await api()).task_snapshot(taskId)
    },
    async cancel_task(taskId) {
      return (await api()).cancel_task(taskId)
    },
  }
}

function waitForPywebview(windowObject: Window): Promise<GameShelfBridge> {
  if (windowObject.pywebview?.api) return Promise.resolve(windowObject.pywebview.api)
  return new Promise((resolve) => {
    windowObject.addEventListener(
      'pywebviewready',
      () => resolve(windowObject.pywebview!.api),
      { once: true },
    )
  })
}
