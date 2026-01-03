import { describe, expect, it } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'

describe('useDraftFromQuery', () => {
  it('sets draft from initialDraft asynchronously and only once', async () => {
    const { result, rerender } = renderHook(({ initial }: { initial: { a: number } | null }) => useDraftFromQuery(initial), {
      initialProps: { initial: null },
    })

    expect(result.current.draft).toBeNull()

    rerender({ initial: { a: 1 } })

    await act(async () => {
      await Promise.resolve()
    })

    expect(result.current.draft).toEqual({ a: 1 })

    rerender({ initial: { a: 2 } })

    await act(async () => {
      await Promise.resolve()
    })

    expect(result.current.draft).toEqual({ a: 1 })
  })

  it('resetToInitial overwrites draft', async () => {
    const { result } = renderHook(() => useDraftFromQuery({ a: 1 }))

    await act(async () => {
      await Promise.resolve()
    })

    act(() => {
      result.current.setDraft({ a: 9 })
    })

    expect(result.current.draft).toEqual({ a: 9 })

    act(() => {
      result.current.resetToInitial()
    })

    expect(result.current.draft).toEqual({ a: 1 })
  })
})

