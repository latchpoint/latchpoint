import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { onboardingService } from './onboarding'

describe('onboarding', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
  })

  it('gets onboarding status', async () => {
    apiMock.get.mockResolvedValue({ onboardingRequired: false })
    const status = await onboardingService.status()
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.onboarding.base)
    expect(status).toEqual({ onboardingRequired: false })
  })

  it('creates onboarding with payload', async () => {
    apiMock.post.mockResolvedValue({ userId: 'u1', email: 'a@example.com' })
    await onboardingService.create({ email: 'a@example.com', password: 'pw' })
    expect(apiMock.post).toHaveBeenCalledWith(apiEndpoints.onboarding.base, {
      email: 'a@example.com',
      password: 'pw',
    })
  })

  it('gets setup status', async () => {
    apiMock.get.mockResolvedValue({ onboardingRequired: false, setupRequired: false, requirements: {} })
    await onboardingService.setupStatus()
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.onboarding.setupStatus)
  })
})
