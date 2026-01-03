import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import api from '@/services/api'
import { apiEndpoints } from '@/services/endpoints'

describe('ApiClient', () => {
  it('primes CSRF cookie and sends X-CSRFToken for unsafe requests', async () => {
    let csrfCalls = 0
    let receivedCsrfHeader: string | null = null

    server.use(
      http.get('/api/auth/csrf/', () => {
        csrfCalls += 1
        document.cookie = 'csrftoken=test-csrf-token'
        return HttpResponse.json({ data: null })
      }),
      http.post('/api/auth/login/', ({ request }) => {
        receivedCsrfHeader = request.headers.get('X-CSRFToken')
        return HttpResponse.json({ data: { ok: true } })
      })
    )

    await api.post(apiEndpoints.auth.login, { email: 'test@example.com', password: 'secret' })

    expect(csrfCalls).toBe(1)
    expect(receivedCsrfHeader).toBe('test-csrf-token')
  })

  it('only primes CSRF once for concurrent unsafe requests', async () => {
    let csrfCalls = 0
    const csrfHeaders: Array<string | null> = []

    server.use(
      http.get('/api/auth/csrf/', () => {
        csrfCalls += 1
        document.cookie = 'csrftoken=test-csrf-token'
        return HttpResponse.json({ data: null })
      }),
      http.post('/api/auth/login/', ({ request }) => {
        csrfHeaders.push(request.headers.get('X-CSRFToken'))
        return HttpResponse.json({ data: { ok: true } })
      })
    )

    await Promise.all([
      api.post(apiEndpoints.auth.login, { email: 'a@example.com', password: 'secret' }),
      api.post(apiEndpoints.auth.login, { email: 'b@example.com', password: 'secret' }),
    ])

    expect(csrfCalls).toBe(1)
    expect(csrfHeaders).toEqual(['test-csrf-token', 'test-csrf-token'])
  })

  it('unwraps envelope meta and camel-cases meta keys in getWithMeta', async () => {
    server.use(
      http.get('/api/example/paginated/', () => {
        return HttpResponse.json({
          data: ['a', 'b'],
          meta: { page: 2, page_size: 5, total: 12, has_next: true, has_previous: false },
        })
      })
    )

    const result = await api.getWithMeta<string[]>('/api/example/paginated/')

    expect(result.data).toEqual(['a', 'b'])
    expect(result.meta).toEqual({
      page: 2,
      pageSize: 5,
      total: 12,
      hasNext: true,
      hasPrevious: false,
    })
  })

  it('throws a typed error from ADR 0025 error envelope responses', async () => {
    server.use(
      http.get('/api/example/error/', () => {
        return HttpResponse.json(
          {
            error: {
              status: 'validation_error',
              message: 'One or more fields failed validation.',
              details: { email: ['Enter a valid email address.'] },
            },
          },
          { status: 400 }
        )
      })
    )

    await expect(api.get('/api/example/error/')).rejects.toMatchObject({
      message: 'One or more fields failed validation.',
      code: '400',
      errorCode: 'validation_error',
      details: { email: ['Enter a valid email address.'] },
    })
  })

  it('snake-cases query params', async () => {
    let receivedUrl: string | null = null

    server.use(
      http.get('/api/example/params/', ({ request }) => {
        receivedUrl = request.url
        return HttpResponse.json({ data: { ok: true } })
      })
    )

    await api.get('/api/example/params/', { pageSize: 5, hasNext: true, fooBar: 'x' })

    expect(receivedUrl).toContain('page_size=5')
    expect(receivedUrl).toContain('has_next=true')
    expect(receivedUrl).toContain('foo_bar=x')
  })

  it('snake-cases request bodies deeply', async () => {
    let receivedJson: unknown = null

    server.use(
      http.post('/api/example/body/', async ({ request }) => {
        receivedJson = await request.json()
        return HttpResponse.json({ data: { ok: true } })
      })
    )

    await api.post('/api/example/body/', {
      fooBar: 1,
      nestedThing: { someKey: 'a' },
      listItems: [{ innerKey: 'b' }],
    })

    expect(receivedJson).toEqual({
      foo_bar: 1,
      nested_thing: { some_key: 'a' },
      list_items: [{ inner_key: 'b' }],
    })
  })

  it('returns undefined for 204 responses', async () => {
    server.use(
      http.delete('/api/example/no-content/', () => {
        return new HttpResponse(null, { status: 204 })
      })
    )

    const result = await api.delete('/api/example/no-content/')
    expect(result).toBeUndefined()
  })
})
