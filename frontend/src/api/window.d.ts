import type { GameShelfBridge } from './contracts'

declare global {
  interface Window {
    pywebview?: {
      api: GameShelfBridge
    }
  }
}

export {}
