export function getMetadataSummary(metadata: Record<string, unknown>): string | null {
  const action = typeof metadata.action === 'string' ? metadata.action : null
  const reason = typeof metadata.reason === 'string' ? metadata.reason : null
  const source = typeof metadata.source === 'string' ? metadata.source : null
  return action || reason || source
}

