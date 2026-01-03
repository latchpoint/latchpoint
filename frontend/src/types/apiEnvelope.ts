// Standardized API response envelope (ADR 0025)

export interface ApiMeta {
  page?: number
  pageSize?: number
  total?: number
  totalPages?: number
  hasNext?: boolean
  hasPrevious?: boolean
  timestamp?: string
}

export interface ApiSuccessResponse<T> {
  data: T
  meta?: ApiMeta
}

export interface ApiErrorBody {
  status: string
  message: string
  details?: Record<string, string[]>
  gateway?: string
  operation?: string
  error?: string
}

export interface ApiErrorResponse {
  error: ApiErrorBody
}

export function isApiErrorEnvelopeResponse(value: unknown): value is ApiErrorResponse {
  if (typeof value !== 'object' || value === null) return false
  if (!('error' in value)) return false
  const err = (value as ApiErrorResponse).error
  return typeof err === 'object' && err !== null && typeof err.message === 'string'
}

export function isApiSuccessEnvelopeResponse<T>(value: unknown): value is ApiSuccessResponse<T> {
  if (typeof value !== 'object' || value === null) return false
  if (!('data' in value) || 'error' in value) return false
  const keys = Object.keys(value as Record<string, unknown>)
  return keys.every((key) => key === 'data' || key === 'meta')
}
