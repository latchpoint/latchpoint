import type { Entity } from '@/types'

/**
 * Extract the Z-Wave JS node ID from an entity's attributes, if present.
 * Handles both camelCase (`nodeId`) and snake_case (`node_id`) keys,
 * and coerces numeric strings like `"5"` to numbers.
 */
export function getZwavejsNodeId(entity: Entity): number | null {
  const attrs = entity.attributes || {}
  const zw = (attrs as Record<string, unknown>).zwavejs
  if (!zw || typeof zw !== 'object') return null
  const nodeId = (zw as Record<string, unknown>).nodeId ?? (zw as Record<string, unknown>).node_id
  if (typeof nodeId === 'number' && Number.isFinite(nodeId)) return nodeId
  if (typeof nodeId === 'string' && /^\d+$/.test(nodeId)) return Number(nodeId)
  return null
}

/**
 * Returns true if the entity is a lock that supports user code management.
 * Currently this means Z-Wave JS locks (CC 99 capable).
 */
export function isCodeCapableLock(entity: Entity): boolean {
  return entity.domain === 'lock' && getZwavejsNodeId(entity) != null
}
