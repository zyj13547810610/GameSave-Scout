export type ApiError = { code: string; message: string; details?: unknown }

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiError }

export type BootstrapState = {
  appName: 'GameShelf'
  schemaVersion: number
  portable: true
}

export type TaskStatus = 'queued' | 'running' | 'completed' | 'cancelled' | 'failed'

export type TaskSnapshot = {
  id: string
  kind: string
  status: TaskStatus
  progress: { completed: number; total: number | null }
  message: string
  result: unknown
  error: ApiError | null
}

export interface GameShelfBridge {
  bootstrap(): Promise<ApiResult<BootstrapState>>
  task_snapshot(taskId: string): Promise<ApiResult<TaskSnapshot>>
  cancel_task(taskId: string): Promise<ApiResult<{ cancelled: boolean }>>
}
