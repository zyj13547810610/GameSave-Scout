import type { SaveLocationKind, SaveLocationSource } from '../../api/contracts'

const kindLabels: Record<SaveLocationKind, string> = {
  directory: '目录',
  file: '单个文件',
  glob: '文件模式',
  registry: '注册表偏好数据',
}

const sourceLabels: Record<SaveLocationSource, string> = {
  manual: '手动添加',
  dynamic: '启动监控',
  ludusavi: 'Ludusavi 清单',
  engine: '引擎提示',
  legacy_scan: '深度扫描',
}

export function saveKindLabel(kind: SaveLocationKind): string {
  return kindLabels[kind]
}

export function saveSourceLabel(source: SaveLocationSource): string {
  return sourceLabels[source]
}

export function confidenceLabel(confidence: number): string {
  if (confidence >= 0.9) return '高置信度'
  if (confidence >= 0.75) return '中置信度'
  return '低置信度'
}

