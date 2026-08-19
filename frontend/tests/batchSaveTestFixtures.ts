import type { BatchSaveCandidate, TaskSnapshot } from '../src/api/contracts'

export function fixtureBatchCandidate(
  overrides: Partial<BatchSaveCandidate> = {},
): BatchSaveCandidate {
  return {
    id: 'candidate-1', scopeKey: 'documents', kind: 'directory',
    displayPath: 'C:\\Users\\Alice\\Documents\\Alice\\Saves',
    availability: 'available', classification: 'installed', confidence: 'high',
    suggestedGameId: 'game-1', suggestedTitle: 'Alice', externalProductId: null,
    engineId: 'unity', strongGroupKey: 'game:game-1', reviewGameId: null,
    reviewStatus: 'pending', saveLocationId: null, sources: ['ludusavi'],
    evidence: ['Ludusavi 精确规则'],
    representativeFiles: [{ name: 'slot1.sav', size: 42, modifiedTimeNs: 100 }],
    matchedFileCount: 1, representativesTruncated: false,
    alternatives: [], lookupQuery: 'Alice',
    firstSeenAt: '2026-08-19T00:00:00+00:00',
    lastSeenAt: '2026-08-19T01:00:00+00:00',
    ...overrides,
  }
}

export function fixtureBatchTask(overrides: Partial<TaskSnapshot> = {}): TaskSnapshot {
  return {
    id: 'batch-task-1', kind: 'batch_save_scan', status: 'running',
    progress: { completed: 1, total: 5 }, message: '正在扫描 Documents',
    details: {}, result: null, error: null, ...overrides,
  }
}
