import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AlarmPanelView } from './AlarmPanelView'

const armButtons = vi.fn()
const quickActions = vi.fn()

vi.mock('./ArmButtons', () => ({
  ArmButtons: (props: any) => {
    armButtons(props)
    return (
      <button type="button" onClick={() => props.onArm('armed_home')}>
        Arm Home
      </button>
    )
  },
}))

vi.mock('./QuickActions', () => ({
  QuickActions: (props: any) => {
    quickActions(props)
    return (
      <button type="button" onClick={props.onDisarm}>
        Disarm
      </button>
    )
  },
}))

vi.mock('./AlarmHistory', () => ({
  AlarmHistory: () => <div>AlarmHistory</div>,
}))

vi.mock('./AlarmStatus', () => ({
  AlarmStatus: () => <div>AlarmStatus</div>,
}))

describe('AlarmPanelView', () => {
  it('renders ArmButtons when disarmed and calls onArm', async () => {
    const user = userEvent.setup()
    const onArm = vi.fn()
    render(
      <AlarmPanelView
        currentState="disarmed"
        countdown={null}
        isArmed={false}
        isDisarmed={true}
        isArming={false}
        isPending={false}
        isTriggered={false}
        availableArmingStates={['armed_home']}
        isLoading={false}
        recentEvents={[]}
        openSensors={[]}
        unknownSensors={[]}
        onArm={onArm}
        onDisarm={vi.fn()}
        onCancelArming={vi.fn()}
      />
    )

    await user.click(screen.getByRole('button', { name: /arm home/i }))
    expect(onArm).toHaveBeenCalledWith('armed_home')
    expect(armButtons).toHaveBeenCalled()
  })

  it('renders QuickActions when armed/pending/triggered and calls onDisarm', async () => {
    const user = userEvent.setup()
    const onDisarm = vi.fn()
    render(
      <AlarmPanelView
        currentState="armed_home"
        countdown={null}
        isArmed={true}
        isDisarmed={false}
        isArming={false}
        isPending={false}
        isTriggered={false}
        availableArmingStates={[]}
        isLoading={false}
        recentEvents={[]}
        openSensors={[]}
        unknownSensors={[]}
        onArm={vi.fn()}
        onDisarm={onDisarm}
        onCancelArming={vi.fn()}
      />
    )

    await user.click(screen.getByRole('button', { name: /disarm/i }))
    expect(onDisarm).toHaveBeenCalled()
    expect(quickActions).toHaveBeenCalled()
  })
})
