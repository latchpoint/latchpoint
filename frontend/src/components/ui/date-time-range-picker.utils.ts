export function parseLocalDateTime(value: string): Date | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  const date = new Date(trimmed)
  if (Number.isNaN(date.getTime())) return null
  return date
}

export function getTimePart(value: string, fallback: string): string {
  const match = value.match(/T(\d{2}:\d{2})/)
  return match?.[1] || fallback
}

export function withDatePreserveTime(existing: string, date: Date, fallbackTime: string): string {
  const time = getTimePart(existing, fallbackTime)
  const yyyy = date.getFullYear()
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}T${time}`
}

export function withTimePreserveDate(existing: string, time: string): string {
  const parsed = parseLocalDateTime(existing)
  if (!parsed) return ''
  const yyyy = parsed.getFullYear()
  const mm = String(parsed.getMonth() + 1).padStart(2, '0')
  const dd = String(parsed.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}T${time}`
}

