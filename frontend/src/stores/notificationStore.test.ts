import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { useNotificationStore } from '@/stores'

describe('notificationStore', () => {
  beforeEach(() => {
    useNotificationStore.getState().clearToasts()
    vi.spyOn(Date, 'now').mockReturnValue(1_000)
    vi.spyOn(Math, 'random').mockReturnValue(0.123456789)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
    useNotificationStore.getState().clearToasts()
  })

  it('adds a toast and prevents duplicates by title+message', () => {
    const addToast = useNotificationStore.getState().addToast

    const id1 = addToast({ type: 'info', title: 'Hello', message: 'World', duration: 0 })
    const id2 = addToast({ type: 'info', title: 'Hello', message: 'World', duration: 0 })

    expect(id1).toBe(id2)
    expect(useNotificationStore.getState().toasts).toHaveLength(1)
  })

  it('auto-removes after duration', async () => {
    vi.useFakeTimers()
    const addToast = useNotificationStore.getState().addToast

    addToast({ type: 'success', title: 'Saved', duration: 1000 })
    expect(useNotificationStore.getState().toasts).toHaveLength(1)

    await vi.advanceTimersByTimeAsync(1000)
    expect(useNotificationStore.getState().toasts).toHaveLength(0)
  })
})

