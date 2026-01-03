import React, { type PropsWithChildren } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import {
  notificationKeys,
  useCreateNotificationProvider,
  useDeleteNotificationProvider,
  useEnabledNotificationProviders,
  useNotificationProvider,
  useNotificationProviders,
  useNotificationProviderTypes,
  useTestNotificationProvider,
  useUpdateNotificationProvider,
} from '@/features/notifications/hooks/useNotificationProviders'

function createClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

function wrap(client: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('notification provider hooks', () => {
  it('lists providers and filters enabled', async () => {
    server.use(
      http.get('/api/notifications/providers/', () => {
        return HttpResponse.json({
          data: [
            { id: 'a', name: 'A', providerType: 'pushbullet', isEnabled: true, config: {} },
            { id: 'b', name: 'B', providerType: 'slack', isEnabled: false, config: {} },
          ],
        })
      })
    )

    const client = createClient()
    const { result } = renderHook(() => useNotificationProviders(), { wrapper: wrap(client) })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(2)

    const { result: enabled } = renderHook(() => useEnabledNotificationProviders(), { wrapper: wrap(client) })
    await waitFor(() => expect(enabled.current.isSuccess).toBe(true))
    expect(enabled.current.data).toHaveLength(1)
    expect(enabled.current.data[0].id).toBe('a')
  })

  it('fetches provider by id when enabled', async () => {
    server.use(
      http.get('/api/notifications/providers/a/', () => {
        return HttpResponse.json({ data: { id: 'a', name: 'A', providerType: 'pushbullet', isEnabled: true, config: {} } })
      })
    )

    const client = createClient()
    const { result } = renderHook(() => useNotificationProvider('a'), { wrapper: wrap(client) })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.id).toBe('a')
  })

  it('fetches provider types', async () => {
    server.use(
      http.get('/api/notifications/provider-types/', () => {
        return HttpResponse.json({ data: { provider_types: [{ id: 'pushbullet', name: 'Pushbullet' }] } })
      })
    )

    const client = createClient()
    const { result } = renderHook(() => useNotificationProviderTypes(), { wrapper: wrap(client) })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.[0]).toMatchObject({ id: 'pushbullet' })
  })

  it('invalidates list after create/update/delete', async () => {
    server.use(
      http.get('/api/notifications/providers/', () => HttpResponse.json({ data: [] })),
      http.post('/api/notifications/providers/', () => HttpResponse.json({ data: { id: 'x' } })),
      http.patch('/api/notifications/providers/x/', () => HttpResponse.json({ data: { id: 'x' } })),
      http.delete('/api/notifications/providers/x/', () => HttpResponse.json({ data: null })),
      http.post('/api/notifications/providers/x/test/', () => HttpResponse.json({ data: { ok: true } }))
    )

    const client = createClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')

    const { result: createHook } = renderHook(() => useCreateNotificationProvider(), { wrapper: wrap(client) })
    await createHook.current.mutateAsync({ name: 'X', providerType: 'pushbullet', config: {} } as any)
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: notificationKeys.all })

    const { result: updateHook } = renderHook(() => useUpdateNotificationProvider(), { wrapper: wrap(client) })
    await updateHook.current.mutateAsync({ id: 'x', data: { name: 'X2', isEnabled: true } as any })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: notificationKeys.all })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: notificationKeys.provider('x') })

    const { result: deleteHook } = renderHook(() => useDeleteNotificationProvider(), { wrapper: wrap(client) })
    await deleteHook.current.mutateAsync('x')
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: notificationKeys.all })

    const { result: testHook } = renderHook(() => useTestNotificationProvider(), { wrapper: wrap(client) })
    await testHook.current.mutateAsync('x')
  })
})

