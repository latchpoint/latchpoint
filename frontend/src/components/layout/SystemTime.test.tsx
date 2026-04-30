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
    // 2026-04-30T03:00:00Z is 12:00:00 in Asia/Tokyo (JST = UTC+9).
    const epochMs = Date.UTC(2026, 3, 30, 3, 0, 0)
    vi.useFakeTimers()
    vi.setSystemTime(epochMs)
    mockSuccess(epochMs, 'Asia/Tokyo')

    const { container } = render(<SystemTime collapsed={false} />)
    expect(container.textContent).toContain('12:00:00')
    // 03:00:00 would only appear if the formatter silently used UTC/browser TZ.
    expect(container.textContent).not.toContain('03:00:00')
  })

  it('ticks the displayed time forward by one second per tick', () => {
    const epochMs = Date.UTC(2026, 3, 30, 3, 0, 0)
    vi.useFakeTimers()
    vi.setSystemTime(epochMs)
    mockSuccess(epochMs, 'UTC')

    const { container } = render(<SystemTime collapsed={false} />)
    expect(container.textContent).toContain('03:00:00')

    act(() => {
      vi.advanceTimersByTime(5_000)
    })
    expect(container.textContent).toContain('03:00:05')
  })

  it('renders HH:MM only in collapsed mode', () => {
    const epochMs = Date.UTC(2026, 3, 30, 3, 0, 45)
    vi.useFakeTimers()
    vi.setSystemTime(epochMs)
    mockSuccess(epochMs, 'UTC')

    const { container } = render(<SystemTime collapsed={true} />)
    expect(container.textContent).toContain('03:00')
    // Seconds should not appear in the visible (non-tooltip) collapsed view.
    expect(container.textContent).not.toContain('03:00:45')
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
