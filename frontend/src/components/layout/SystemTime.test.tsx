import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render } from '@testing-library/react'

import { SystemTime } from './SystemTime'

vi.mock('@/hooks/useServerTime', () => ({
  useServerTimeQuery: vi.fn(),
}))

import { useServerTimeQuery } from '@/hooks/useServerTime'

const mockedUseServerTime = vi.mocked(useServerTimeQuery)

function mockSuccess(epochMs: number, timezone: string) {
  mockedUseServerTime.mockReturnValue({
    isSuccess: true,
    data: {
      timestamp: new Date(epochMs).toISOString(),
      timezone,
      epochMs,
      formatted: '',
    },
    dataUpdatedAt: epochMs,
  } as unknown as ReturnType<typeof useServerTimeQuery>)
}

function mockLoading() {
  mockedUseServerTime.mockReturnValue({
    isSuccess: false,
    data: undefined,
    dataUpdatedAt: 0,
  } as unknown as ReturnType<typeof useServerTimeQuery>)
}

describe('SystemTime', () => {
  beforeEach(() => {
    mockedUseServerTime.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows expanded placeholder when data is not loaded', () => {
    mockLoading()
    const { container } = render(<SystemTime collapsed={false} />)
    expect(container.textContent).toContain('--:--:--')
  })

  it('shows collapsed placeholder when data is not loaded', () => {
    mockLoading()
    const { container } = render(<SystemTime collapsed={true} />)
    expect(container.textContent).toContain('--:--')
    expect(container.textContent).not.toContain('--:--:--')
  })

  it("renders the server's wall-clock, not the browser's TZ (regression: JS Date silent reformat)", () => {
    // 2026-04-30T03:00:00Z is 12:00 in Asia/Tokyo (JST = UTC+9).
    const epochMs = Date.UTC(2026, 3, 30, 3, 0, 0)
    vi.useFakeTimers()
    vi.setSystemTime(epochMs)
    mockSuccess(epochMs, 'Asia/Tokyo')

    // Compute the expected/wrong strings with the same Intl options the
    // component uses. This keeps the assertions locale-agnostic — what
    // matters is that Tokyo wall-clock appears and UTC wall-clock does not.
    const opts = { dateStyle: 'short', timeStyle: 'long' } as const
    const tokyoStr = new Intl.DateTimeFormat(undefined, { timeZone: 'Asia/Tokyo', ...opts }).format(
      new Date(epochMs)
    )
    const utcStr = new Intl.DateTimeFormat(undefined, { timeZone: 'UTC', ...opts }).format(
      new Date(epochMs)
    )

    const { container } = render(<SystemTime collapsed={false} />)
    expect(container.textContent).toContain(tokyoStr)
    expect(container.textContent).not.toContain(utcStr)
  })

  it('ticks the displayed time forward by one second per tick', () => {
    const epochMs = Date.UTC(2026, 3, 30, 3, 0, 0)
    vi.useFakeTimers()
    vi.setSystemTime(epochMs)
    mockSuccess(epochMs, 'UTC')

    const opts = { timeZone: 'UTC', dateStyle: 'short', timeStyle: 'long' } as const
    const initialStr = new Intl.DateTimeFormat(undefined, opts).format(new Date(epochMs))
    const advancedStr = new Intl.DateTimeFormat(undefined, opts).format(new Date(epochMs + 5_000))

    const { container } = render(<SystemTime collapsed={false} />)
    expect(container.textContent).toContain(initialStr)

    act(() => {
      vi.advanceTimersByTime(5_000)
    })
    expect(container.textContent).toContain(advancedStr)
  })

  it('renders without seconds in collapsed mode', () => {
    const epochMs = Date.UTC(2026, 3, 30, 3, 0, 45)
    vi.useFakeTimers()
    vi.setSystemTime(epochMs)
    mockSuccess(epochMs, 'UTC')

    const shortStr = new Intl.DateTimeFormat(undefined, {
      timeZone: 'UTC',
      timeStyle: 'short',
    }).format(new Date(epochMs))
    const longStr = new Intl.DateTimeFormat(undefined, {
      timeZone: 'UTC',
      timeStyle: 'long',
    }).format(new Date(epochMs))

    const { container } = render(<SystemTime collapsed={true} />)
    expect(container.textContent).toContain(shortStr)
    // The long form (which includes seconds) should NOT appear in the visible collapsed view.
    expect(container.textContent).not.toContain(longStr)
  })

  it('clears the tick interval on unmount', () => {
    vi.useFakeTimers()
    const epochMs = Date.UTC(2026, 3, 30, 3, 0, 0)
    vi.setSystemTime(epochMs)
    mockSuccess(epochMs, 'UTC')

    const { unmount } = render(<SystemTime collapsed={false} />)
    const clearSpy = vi.spyOn(window, 'clearInterval')
    unmount()
    expect(clearSpy).toHaveBeenCalled()
  })
})
