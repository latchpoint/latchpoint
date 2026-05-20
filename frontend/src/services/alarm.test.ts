import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
  getPaginated: vi.fn(),
  getPaginatedItems: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { alarmService } from './alarm'

describe('alarm', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.patch.mockReset()
    apiMock.delete.mockReset()
    apiMock.getPaginated.mockReset()
    apiMock.getPaginatedItems.mockReset()
  })

  it('arms via POST', async () => {
    apiMock.post.mockResolvedValue({ state: 'armed_home' })
    await alarmService.arm({ state: 'armed_home' } as any)
    expect(apiMock.post).toHaveBeenCalledWith(apiEndpoints.alarm.arm, { state: 'armed_home' })
  })

  it('cancels arming with optional code', async () => {
    apiMock.post.mockResolvedValue({ state: 'disarmed' })
    await alarmService.cancelArming('1234')
    expect(apiMock.post).toHaveBeenCalledWith(apiEndpoints.alarm.cancelArming, { code: '1234' })
  })

  it('fetches recent events using paginated items helper', async () => {
    apiMock.getPaginatedItems.mockResolvedValue([])
    await alarmService.getRecentEvents(5)
    expect(apiMock.getPaginatedItems).toHaveBeenCalledWith(apiEndpoints.events.all, {
      pageSize: 5,
      ordering: '-timestamp',
    })
  })

  it('acknowledges event via PATCH with empty body', async () => {
    apiMock.patch.mockResolvedValue({ id: 1 })
    await alarmService.acknowledgeEvent(1)
    expect(apiMock.patch).toHaveBeenCalledWith(apiEndpoints.events.acknowledge(1), {})
  })

  describe('getSettings', () => {
    it('handles nested { profile, entries } format', async () => {
      apiMock.get.mockResolvedValue({
        profile: { id: 1, name: 'Default', isActive: true, createdAt: '2025-01-01', updatedAt: '2025-01-01' },
        entries: [
          { key: 'code_arm_required', value: false },
          { key: 'available_arming_states', value: ['armed_home'] },
          { key: 'audio_visual_settings', value: { beepEnabled: false, countdownDisplayEnabled: true, colorCodingEnabled: true } },
          { key: 'sensor_behavior', value: { warnOnOpenSensors: true, autoBypassEnabled: false, forceArmEnabled: true } },
        ],
      })
      const result = await alarmService.getSettings()
      expect(result.id).toBe(1)
      expect(result.codeArmRequired).toBe(false)
      expect(result.availableArmingStates).toEqual(['armed_home'])
    })

    it('handles flat format (settings inlined)', async () => {
      apiMock.get.mockResolvedValue({
        id: 1,
        name: 'Default',
        isActive: true,
        createdAt: '2025-01-01',
        updatedAt: '2025-01-01',
        codeArmRequired: false,
        availableArmingStates: ['armed_away', 'armed_home'],
        audioVisualSettings: { beepEnabled: true, countdownDisplayEnabled: true, colorCodingEnabled: true },
        sensorBehavior: { warnOnOpenSensors: true, autoBypassEnabled: false, forceArmEnabled: true },
      })
      const result = await alarmService.getSettings()
      expect(result.id).toBe(1)
      expect(result.codeArmRequired).toBe(false)
      expect(result.availableArmingStates).toEqual(['armed_away', 'armed_home'])
    })

    it('provides defaults when flat format has missing fields', async () => {
      apiMock.get.mockResolvedValue({
        id: 2,
        name: 'Sparse',
        isActive: true,
        createdAt: '2025-01-01',
        updatedAt: '2025-01-01',
      })
      const result = await alarmService.getSettings()
      expect(result.codeArmRequired).toBe(true)
      expect(result.availableArmingStates).toEqual([])
    })
  })
})
