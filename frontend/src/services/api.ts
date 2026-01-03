import { API_BASE_URL, CSRF_COOKIE_NAME, CSRF_HEADER_NAME } from '@/lib/constants'
import type { ApiError, PaginatedResponse } from '@/types'
import { isRecord } from '@/lib/typeGuards'
import { isApiErrorResponse, getApiErrorMessage } from '@/types/errors'
import {
  isApiErrorEnvelopeResponse,
  isApiSuccessEnvelopeResponse,
  type ApiMeta,
} from '@/types/apiEnvelope'
import { apiEndpoints } from './endpoints'

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value) &&
    Object.prototype.toString.call(value) === '[object Object]'
  )
}

function toCamelCaseKey(key: string): string {
  if (!key.includes('_')) return key
  const camel = key.replace(/_([a-z0-9])/g, (_, next: string) =>
    /[a-z]/.test(next) ? next.toUpperCase() : next
  )
  // Preserve common acronyms that appear as snake_case in API responses.
  return camel.replace(/2fa/g, '2FA')
}

function toSnakeCaseKey(key: string): string {
  return key
    .replace(/([A-Z])/g, '_$1')
    .replace(/__/g, '_')
    .toLowerCase()
}

function transformKeysDeep(value: unknown, transformKey: (key: string) => string): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => transformKeysDeep(item, transformKey))
  }
  if (!isPlainObject(value)) return value
  const out: Record<string, unknown> = {}
  for (const [key, nested] of Object.entries(value)) {
    out[transformKey(key)] = transformKeysDeep(nested, transformKey)
  }
  return out
}

function getCookieValue(cookieName: string): string | null {
  if (typeof document === 'undefined') return null
  const cookies = document.cookie ? document.cookie.split('; ') : []
  for (const cookie of cookies) {
    const [name, ...rest] = cookie.split('=')
    if (name === cookieName) {
      return decodeURIComponent(rest.join('='))
    }
  }
  return null
}

class ApiClient {
  private baseUrl: string
  private csrfPromise: Promise<void> | null = null

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl
  }

  private resolveUrl(endpoint: string): string {
    if (this.baseUrl) {
      return `${this.baseUrl}${endpoint}`
    }
    if (typeof window === 'undefined') {
      return endpoint
    }
    return new URL(endpoint, window.location.origin).toString()
  }

  private async ensureCsrfCookie(): Promise<void> {
    if (this.csrfPromise) return this.csrfPromise

    this.csrfPromise = fetch(this.resolveUrl(apiEndpoints.auth.csrf), {
      method: 'GET',
      credentials: 'include',
    })
      .then(() => undefined)
      .finally(() => {
        this.csrfPromise = null
      })

    return this.csrfPromise
  }

  private async getCsrfToken(): Promise<string | null> {
    const existing = getCookieValue(CSRF_COOKIE_NAME)
    if (existing) return existing
    await this.ensureCsrfCookie()
    return getCookieValue(CSRF_COOKIE_NAME)
  }

  private async rawRequest(
    method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
    endpoint: string,
    options?: {
      params?: Record<string, string | number | boolean | undefined>
      data?: unknown
    }
  ): Promise<Response> {
    const buildUrl = (): URL => {
      const url = new URL(this.resolveUrl(endpoint))
      if (options?.params) {
        const snakeParams = transformKeysDeep(options.params, toSnakeCaseKey) as Record<
          string,
          string | number | boolean | undefined
        >
        Object.entries(snakeParams).forEach(([key, value]) => {
          if (value !== undefined) url.searchParams.append(key, String(value))
        })
      }
      return url
    }

    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (method === 'POST' || method === 'PUT' || method === 'PATCH' || method === 'DELETE') {
      headers[CSRF_HEADER_NAME] = (await this.getCsrfToken()) || ''
    }
    return fetch(buildUrl().toString(), {
      method,
      headers,
      credentials: 'include',
      body:
        method === 'GET'
          ? undefined
          : options?.data
            ? JSON.stringify(transformKeysDeep(options.data, toSnakeCaseKey))
            : undefined,
    })
  }

  private async request<T>(
    method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
    endpoint: string,
    options?: {
      params?: Record<string, string | number | boolean | undefined>
      data?: unknown
    }
  ): Promise<T> {
    const response = await this.rawRequest(method, endpoint, options)
    return this.handleResponse<T>(response)
  }

  private async handleResponse<T>(response: Response): Promise<T> {
    if (!response.ok) {
      const parsed = await response.json().catch(() => null)
      const error: ApiError = (() => {
        if (isApiErrorEnvelopeResponse(parsed)) {
          return {
            message: parsed.error.message,
            code: response.status.toString(),
            errorCode: parsed.error.status,
            details: parsed.error.details,
            gateway: parsed.error.gateway,
            operation: parsed.error.operation,
            error: parsed.error.error,
          }
        }

        if (isApiErrorResponse(parsed)) {
          const message = getApiErrorMessage(parsed)
          const code = isRecord(parsed) && typeof parsed.code === 'string'
            ? parsed.code
            : response.status.toString()
          const details = isRecord(parsed) && isRecord(parsed.details)
            ? (parsed.details as Record<string, string[]>)
            : undefined
          const errorCode = isRecord(parsed) && typeof parsed.error_code === 'string'
            ? (parsed.error_code as string)
            : undefined
          const gateway = isRecord(parsed) && typeof parsed.gateway === 'string'
            ? (parsed.gateway as string)
            : undefined
          const operation = isRecord(parsed) && typeof parsed.operation === 'string'
            ? (parsed.operation as string)
            : undefined
          const gatewayError = isRecord(parsed) && typeof parsed.error === 'string'
            ? (parsed.error as string)
            : undefined

          return { message, code, details, errorCode, gateway, operation, error: gatewayError }
        }
        return {
          message: response.statusText || 'An error occurred',
          code: response.status.toString(),
        }
      })()
      throw error
    }

    // Handle 204 No Content - return undefined for empty responses
    // Note: This may cause type issues if T expects an object. Callers should handle this.
    if (response.status === 204) {
      return undefined as T
    }

    const json = await response.json()
    const transformed = transformKeysDeep(json, toCamelCaseKey)

    // ADR 0025 envelope success: unwrap to the payload by default.
    if (isApiSuccessEnvelopeResponse<T>(transformed)) {
      return transformed.data
    }

    // Legacy/transition fallback.
    return transformed as T
  }

  async get<T>(endpoint: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
    return this.request<T>('GET', endpoint, { params })
  }

  async getData<T>(
    endpoint: string,
    params?: Record<string, string | number | boolean | undefined>
  ): Promise<T> {
    return this.get<T>(endpoint, params)
  }

  async getPaginated<T>(
    endpoint: string,
    params?: Record<string, string | number | boolean | undefined>
  ): Promise<PaginatedResponse<T>> {
    const { data, meta } = await this.getWithMeta<T[]>(endpoint, params)
    return {
      data,
      total: meta?.total ?? data.length,
      page: meta?.page ?? 1,
      pageSize: meta?.pageSize ?? data.length,
      totalPages: meta?.totalPages ?? 1,
      hasNext: meta?.hasNext ?? false,
      hasPrevious: meta?.hasPrevious ?? false,
    }
  }

  async getPaginatedItems<T>(
    endpoint: string,
    params?: Record<string, string | number | boolean | undefined>
  ): Promise<T[]> {
    const response = await this.getPaginated<T>(endpoint, params)
    return response.data
  }

  async post<T>(endpoint: string, data?: unknown): Promise<T> {
    return this.request<T>('POST', endpoint, { data })
  }

  async postData<T>(endpoint: string, data?: unknown): Promise<T> {
    return this.post<T>(endpoint, data)
  }

  async put<T>(endpoint: string, data: unknown): Promise<T> {
    return this.request<T>('PUT', endpoint, { data })
  }

  async patch<T>(endpoint: string, data: unknown): Promise<T> {
    return this.request<T>('PATCH', endpoint, { data })
  }

  async delete<T>(endpoint: string, data?: unknown): Promise<T> {
    return this.request<T>('DELETE', endpoint, { data })
  }

  async getWithMeta<T>(
    endpoint: string,
    params?: Record<string, string | number | boolean | undefined>
  ): Promise<{ data: T; meta?: ApiMeta }> {
    const response = await this.rawRequest('GET', endpoint, { params })

    if (!response.ok) {
      await this.handleResponse<unknown>(response)
      throw new Error('Unreachable')
    }

    if (response.status === 204) {
      return { data: undefined as T }
    }

    const json = await response.json()
    const transformed = transformKeysDeep(json, toCamelCaseKey)

    if (isApiSuccessEnvelopeResponse<T>(transformed)) {
      return { data: transformed.data, meta: transformed.meta }
    }

    // Legacy paginated shape: { data: [...], total, page, ... }
    if (isRecord(transformed) && 'data' in transformed) {
      const meta: ApiMeta = {}
      if (typeof transformed.total === 'number') meta.total = transformed.total
      if (typeof transformed.page === 'number') meta.page = transformed.page
      if (typeof transformed.pageSize === 'number') meta.pageSize = transformed.pageSize
      if (typeof transformed.totalPages === 'number') meta.totalPages = transformed.totalPages
      if (typeof transformed.hasNext === 'boolean') meta.hasNext = transformed.hasNext
      if (typeof transformed.hasPrevious === 'boolean') meta.hasPrevious = transformed.hasPrevious
      if (typeof transformed.timestamp === 'string') meta.timestamp = transformed.timestamp

      return { data: transformed.data as T, meta: Object.keys(meta).length ? meta : undefined }
    }

    return { data: transformed as T }
  }
}

export const api = new ApiClient()
export default api
