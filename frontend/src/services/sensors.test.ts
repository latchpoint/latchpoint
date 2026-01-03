import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { sensorsService } from './sensors'

describe('sensors', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.patch.mockReset()
    apiMock.delete.mockReset()
  })

  it('creates a sensor via POST', async () => {
    apiMock.post.mockResolvedValue({ id: 1 })
    await sensorsService.createSensor({ name: 'Door', entityId: 'binary_sensor.door', isActive: true, isEntryPoint: false })
    expect(apiMock.post).toHaveBeenCalledWith(apiEndpoints.sensors.all, {
      name: 'Door',
      entityId: 'binary_sensor.door',
      isActive: true,
      isEntryPoint: false,
    })
  })

  it('deletes a sensor by id', async () => {
    apiMock.delete.mockResolvedValue(undefined)
    await sensorsService.deleteSensor(2)
    expect(apiMock.delete).toHaveBeenCalledWith(apiEndpoints.sensors.detail(2))
  })
})
