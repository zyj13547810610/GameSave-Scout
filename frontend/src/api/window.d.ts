import type { GameSaveScoutBridge } from './contracts'

declare global {
  interface Window {
    pywebview?: {
      api: GameSaveScoutBridge
    }
  }
}

export {}
