import { describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useAlarmSettingsTabModel } from '@/features/alarmSettings/hooks/useAlarmSettingsTabModel'
import { AlarmState } from '@/lib/constants'

const mutateAsync = vi.fn().mockResolvedValue({ notice: 'ok' })

vi.mock('@/hooks/useAuthQueries', () => {
  return { useCurrentUserQuery: () => ({ data: { role: 'admin' } }) }
})

vi.mock('@/hooks/useAlarmQueries', () => {
  return {
    useAlarmSettingsQuery: () => ({
      isLoading: false,
      error: null,
      data: {
        id: 1,
        name: 'Default',
        isActive: true,
        codeArmRequired: true,
        availableArmingStates: [AlarmState.ARMED_HOME],
        audioVisualSettings: { beepEnabled: true, countdownDisplayEnabled: true, colorCodingEnabled: true },
        sensorBehavior: { warnOnOpenSensors: false, autoBypassEnabled: false, forceArmEnabled: false },
        createdAt: '2025-01-01T00:00:00Z',
        updatedAt: '2025-01-01T00:00:00Z',
      },
    }),
  }
})

vi.mock('@/hooks/useSettingsQueries', () => {
  return {
    useUpdateSettingsProfileMutation: () => ({ isPending: false, mutateAsync }),
  }
})

describe('useAlarmSettingsTabModel', () => {
  it('requires at least one arm mode', async () => {
    const { result } = renderHook(() => useAlarmSettingsTabModel())

    act(() => {
      result.current.setDraft({
        codeArmRequired: false,
        availableArmingStates: [],
      })
    })

    await act(async () => {
      await result.current.save()
    })

    expect(result.current.error).toBe('Select at least one arm mode.')
    expect(mutateAsync).not.toHaveBeenCalled()
  })

  it('writes expected settings entries on save', async () => {
    const { result } = renderHook(() => useAlarmSettingsTabModel())

    act(() => {
      result.current.setDraft({
        codeArmRequired: true,
        availableArmingStates: [AlarmState.ARMED_HOME],
      })
    })

    await act(async () => {
      await result.current.save()
    })

    expect(mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 1,
        changes: expect.objectContaining({
          entries: expect.arrayContaining([
            { key: 'code_arm_required', value: true },
            { key: 'available_arming_states', value: [AlarmState.ARMED_HOME] },
          ]),
        }),
      }),
    )
    expect(result.current.notice).toBe('Saved alarm settings.')
  })
})
