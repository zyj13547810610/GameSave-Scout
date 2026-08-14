import { describe, expect, it } from 'vitest'
import { createBridge } from '../src/api/bridge'

describe('desktop bridge', () => {
  it('uses the development mock when pywebview is absent', async () => {
    const bridge = createBridge({ windowObject: {} as Window })

    const result = await bridge.bootstrap()

    expect(result).toEqual({
      ok: true,
      data: { appName: 'GameShelf', schemaVersion: 1, portable: true, uiScale: 1 },
    })
  })
})
