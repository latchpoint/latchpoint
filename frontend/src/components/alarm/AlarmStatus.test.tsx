import React from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AlarmStatus } from '@/components/alarm/AlarmStatus'
import { AlarmState } from '@/lib/constants'

describe('AlarmStatus', () => {
  it('renders label for state', () => {
    render(<AlarmStatus state={AlarmState.DISARMED} />)
    expect(screen.getByText(/disarmed/i)).toBeInTheDocument()
  })

  it('hides label when showLabel is false', () => {
    render(<AlarmStatus state={AlarmState.DISARMED} showLabel={false} />)
    expect(screen.queryByText(/disarmed/i)).toBeNull()
  })
})

