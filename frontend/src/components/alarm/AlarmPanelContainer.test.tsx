import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from '@testing-library/react'
import { AlarmPanelContainer } from './AlarmPanelContainer'

let state: any
const arm = vi.fn()
const disarm = vi.fn()
const cancelArming = vi.fn()
const openModal = vi.fn()
const handleError = vi.fn()
const recentEventsQuery = { data: [] as any[] }

vi.mock('@/hooks/useAlarmState', () => ({ useAlarmState: () => state }))
vi.mock('@/hooks/useAlarmActions', () => ({
  useAlarmActions: () => ({ arm, disarm, cancelArming, isPending: false }),
}))
vi.mock('@/hooks/useAlarmValidation', () => ({
  useAlarmValidation: () => ({ openSensors: [], unknownSensors: [] }),
}))
vi.mock('@/hooks/useAlarmQueries', () => ({
  useRecentEventsQuery: () => recentEventsQuery,
}))
vi.mock('@/stores/modalStore', () => ({
  useModal: () => ({ open: openModal }),
}))
vi.mock('@/lib/errorHandler', () => ({
  handleError: (e: unknown) => handleError(e),
}))

const captured: any[] = []
vi.mock('./AlarmPanelView', () => ({
  AlarmPanelView: (props: any) => {
    captured.push(props)
    return <div>AlarmPanelView</div>
  },
}))

describe('AlarmPanelContainer', () => {
  beforeEach(() => {
    captured.length = 0
    arm.mockReset().mockResolvedValue(undefined)
    disarm.mockReset().mockResolvedValue(undefined)
    cancelArming.mockReset().mockResolvedValue(undefined)
    openModal.mockReset()
    handleError.mockReset()
    state = {
      currentState: 'disarmed',
      countdown: null,
      isArmed: false,
      isDisarmed: true,
      isArming: false,
      isPending: false,
      isTriggered: false,
      availableArmingStates: ['armed_home'],
      isLoading: false,
      codeRequiredForArm: true,
    }
  })

  it('opens code-entry modal when arming requires a code', async () => {
    render(<AlarmPanelContainer />)
    const props = captured.at(-1)

    props.onArm('armed_home')
    expect(openModal).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Enter Code to Arm',
        submitLabel: 'Arm',
        onSubmit: expect.any(Function),
      })
    )

    const modalArgs = openModal.mock.calls[0][0]
    await modalArgs.onSubmit('1234')
    expect(arm).toHaveBeenCalledWith('armed_home', '1234')
  })

  it('opens code-entry modal for disarm', async () => {
    render(<AlarmPanelContainer />)
    const props = captured.at(-1)

    props.onDisarm()
    expect(openModal).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Enter Code to Disarm',
        submitLabel: 'Disarm',
        onSubmit: expect.any(Function),
      })
    )

    const modalArgs = openModal.mock.calls[0][0]
    await modalArgs.onSubmit('9999')
    expect(disarm).toHaveBeenCalledWith('9999')
  })
})
