import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ArmButtons } from '@/components/alarm/ArmButtons'
import { AlarmState } from '@/lib/constants'

describe('ArmButtons', () => {
  it('disables current state and calls onArm for others', async () => {
    const user = userEvent.setup()
    const onArm = vi.fn()

    render(<ArmButtons onArm={onArm} currentState={AlarmState.ARMED_HOME} />)

    expect(screen.getByRole('button', { name: /home/i })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /away/i }))
    expect(onArm).toHaveBeenCalledWith(AlarmState.ARMED_AWAY)
  })
})

