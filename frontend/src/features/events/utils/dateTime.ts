import { formatDistanceToNow } from 'date-fns'

export function toUtcIsoFromDatetimeLocal(value: string): string | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  const date = new Date(trimmed)
  if (Number.isNaN(date.getTime())) return null
  return date.toISOString()
}

export function formatEventTimeRelative(timestamp: string): string {
  try {
    return formatDistanceToNow(new Date(timestamp), { addSuffix: true })
  } catch {
    return timestamp
  }
}

export function formatEventTimeAbsolute(timestamp: string): string {
  try {
    return new Date(timestamp).toLocaleString()
  } catch {
    return timestamp
  }
}

