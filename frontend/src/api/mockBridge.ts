import type { GameShelfBridge } from './contracts'

export function createMockBridge(): GameShelfBridge {
  return {
    async bootstrap() {
      return {
        ok: true,
        data: { appName: 'GameShelf', schemaVersion: 1, portable: true },
      }
    },
    async task_snapshot() {
      return {
        ok: false,
        error: { code: 'task_not_found', message: '没有找到对应的后台任务。' },
      }
    },
    async cancel_task() {
      return { ok: true, data: { cancelled: false } }
    },
  }
}
