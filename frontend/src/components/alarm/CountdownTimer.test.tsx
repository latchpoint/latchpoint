import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { CountdownTimer } from '@/components/alarm/CountdownTimer'

describe('CountdownTimer', () => {
  it('formats time as MM:SS for >=60 seconds', () => {
    render(<CountdownTimer remainingSeconds={61} totalSeconds={100} type="entry" />)
    expect(screen.getByText('1:01')).toBeInTheDocument()
  })

  it('counts down and calls onComplete', async () => {
    vi.useFakeTimers()
    const onComplete = vi.fn()

    render(<CountdownTimer remainingSeconds={2} totalSeconds={2} type="exit" onComplete={onComplete} />)
    expect(screen.getByText('2')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(screen.getByText('1')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(screen.getByText('0')).toBeInTheDocument()
    expect(onComplete).toHaveBeenCalled()

    vi.useRealTimers()
  })
})
