import { describe, expect, it } from 'vitest'
import { createBridge, createDeferredBridge, ruleBridgeMethods } from '../src/api/bridge'
import type { GameSaveScoutBridge } from '../src/api/contracts'

describe('desktop bridge', () => {
  it('uses the development mock when pywebview is absent', async () => {
    const bridge = createBridge({ windowObject: {} as Window })

    const result = await bridge.bootstrap()

    expect(result).toEqual({
      ok: true,
      data: {
        appName: 'GameSave Scout', schemaVersion: 4, portable: true, uiScale: 1,
        libraryScanSettings: { startupQuickScan: true, scanConcurrency: 1 },
        coverWizardSettings: {
          coverOnlineEnabled: false,
          coverVndbCandidateLimit: 5,
          coverLocalScanCandidateLimit: 10,
          coverOptimizeEnabled: true,
          coverLocalScanDepth: 2,
        },
        batchSaveSettings: { customRoots: [] },
      },
    })
  })

  it('forwards every rule method after delayed pywebview readiness', async () => {
    let ready: (() => void) | undefined
    const windowObject = {
      addEventListener(_name: string, callback: () => void) { ready = callback },
    } as unknown as Window
    const bridge = createDeferredBridge(windowObject)
    const pending = ruleBridgeMethods.map((name) => (
      (bridge[name] as (input: Record<string, never>) => Promise<unknown>)({})
    ))
    const calls: string[] = []
    const api = Object.fromEntries(ruleBridgeMethods.map((name) => [
      name,
      async () => { calls.push(name); return { ok: true, data: name } },
    ])) as unknown as GameSaveScoutBridge
    Object.assign(windowObject, { pywebview: { api } })
    ready?.()

    await Promise.all(pending)
    expect(calls).toEqual([...ruleBridgeMethods])
  })
})
