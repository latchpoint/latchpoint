import React, { type PropsWithChildren } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import {
  useControlPanelsQuery,
  useCreateControlPanelMutation,
  useDeleteControlPanelMutation,
  useUpdateControlPanelMutation,
} from '@/hooks/useControlPanels'
import { queryKeys } from '@/types'

vi.mock('@/hooks/useAuthQueries', () => {
  return {
    useAuthSessionQuery: () => ({ data: { isAuthenticated: true } }),
    useCurrentUserQuery: () => ({ data: { role: 'admin' } }),
  }
})

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

describe('useControlPanels', () => {
  it('fetches panels when authenticated admin', async () => {
    server.use(
      http.get('/api/control-panels/', () => {
        return HttpResponse.json({ data: [] })
      })
    )

    const client = createClient()
    const { result } = renderHook(() => useControlPanelsQuery(), { wrapper: wrap(client) })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual([])
  })

  it('invalidates controlPanels query after create/update/delete', async () => {
    server.use(
      http.post('/api/control-panels/', () => HttpResponse.json({ data: { id: 1 } })),
      http.patch('/api/control-panels/1/', () => HttpResponse.json({ data: { id: 1 } })),
      http.delete('/api/control-panels/1/', () => HttpResponse.json({ data: null }))
    )

    const client = createClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')

    const { result: createHook } = renderHook(() => useCreateControlPanelMutation(), { wrapper: wrap(client) })
    await createHook.current.mutateAsync({ name: 'x', kind: 'ring_keypad_v2', enabled: true } as any)
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.controlPanels.all })

    const { result: updateHook } = renderHook(() => useUpdateControlPanelMutation(), { wrapper: wrap(client) })
    await updateHook.current.mutateAsync({ id: 1, changes: { enabled: true } } as any)
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.controlPanels.all })

    const { result: deleteHook } = renderHook(() => useDeleteControlPanelMutation(), { wrapper: wrap(client) })
    await deleteHook.current.mutateAsync(1)
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.controlPanels.all })
  })
})

