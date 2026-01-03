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
})
