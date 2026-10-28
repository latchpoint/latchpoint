import { createElement, type PropsWithChildren } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import { queryKeys } from '@/types'
import type { DoorCode } from '@/types'
import { useDeleteDoorCodeMutation, useReadCachedDoorCode, useRetryDoorCodePushMutation } from './useDoorCodesQueries'

function createClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

function wrap(client: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return createElement(QueryClientProvider, { client }, children)
  }
}

describe('useDoorCodesQueries', () => {
  it('imports', async () => {
    const mod = await import('./useDoorCodesQueries')
    expect(mod).toBeTruthy()
  })

  it('rejects Retry with the API message and still refetches the codes', async () => {
    server.use(
      http.post('/api/door-codes/7/push/', () =>
        HttpResponse.json(
          {
            error: {
              status: 'conflict',
              message: 'Door code is inactive. Turn it on before pushing it to its locks.',
            },
          },
          { status: 409 },
        ),
      ),
    )

    const client = createClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')
    const { result } = renderHook(() => useRetryDoorCodePushMutation('user-1'), { wrapper: wrap(client) })

    await expect(result.current.mutateAsync(7)).rejects.toMatchObject({
      message: 'Door code is inactive. Turn it on before pushing it to its locks.',
      code: '409',
    })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.doorCodes.byUser('user-1') })
  })

  it('rejects a refused delete with the API message and still refetches the codes', async () => {
    const message =
      "Couldn't clear slot 3 on lock.front_door, it may still hold the PIN. The door code wasn't deleted and is now off, try again when the lock responds."
    server.use(
      http.delete('/api/door-codes/7/', () =>
        HttpResponse.json({ error: { status: 'gateway_error', message, gateway: 'zwavejs' } }, { status: 502 }),
      ),
    )

    const client = createClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')
    const { result } = renderHook(() => useDeleteDoorCodeMutation('user-1'), { wrapper: wrap(client) })

    await expect(result.current.mutateAsync({ id: 7, reauthPassword: 'pw' })).rejects.toMatchObject({
      message,
      code: '502',
    })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.doorCodes.byUser('user-1') })
  })

  it('refetches the codes after a delete that works', async () => {
    server.use(http.delete('/api/door-codes/7/', () => new HttpResponse(null, { status: 204 })))

    const client = createClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')
    const { result } = renderHook(() => useDeleteDoorCodeMutation('user-1'), { wrapper: wrap(client) })

    await result.current.mutateAsync({ id: 7, reauthPassword: 'pw' })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.doorCodes.byUser('user-1') })
  })

  it('reads a door code and when it was fetched from the cache', () => {
    const client = createClient()
    const code = { id: 7, userId: 'someone-else' } as DoorCode
    client.setQueryData(queryKeys.doorCodes.byUser('user-1'), [code], { updatedAt: 1234 })
    const { result } = renderHook(() => useReadCachedDoorCode('user-1'), { wrapper: wrap(client) })

    expect(result.current(7)).toEqual({ code, dataUpdatedAt: 1234 })
    expect(result.current(8)).toBeNull()
  })

  it('reads nothing when the codes for that user are not cached', () => {
    const client = createClient()
    const { result } = renderHook(() => useReadCachedDoorCode('user-1'), { wrapper: wrap(client) })

    expect(result.current(7)).toBeNull()
  })

  it('refetches the codes after a successful Retry', async () => {
    server.use(http.post('/api/door-codes/7/push/', () => HttpResponse.json({ data: { id: 7 } })))

    const client = createClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')
    const { result } = renderHook(() => useRetryDoorCodePushMutation('user-1'), { wrapper: wrap(client) })

    await result.current.mutateAsync(7)
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.doorCodes.byUser('user-1') })
  })
})
