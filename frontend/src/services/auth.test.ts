import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { authService } from './auth'

describe('auth', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
  })

  it('logs in via POST', async () => {
    apiMock.post.mockResolvedValue({ ok: true })
    await authService.login({ email: 'a@example.com', password: 'pw' } as any)
    expect(apiMock.post).toHaveBeenCalledWith(apiEndpoints.auth.login, {
      email: 'a@example.com',
      password: 'pw',
    })
  })

  it('gets current user', async () => {
    apiMock.get.mockResolvedValue({ id: 'u1' })
    await authService.getCurrentUser()
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.users.me)
  })

  it('verifies 2FA code', async () => {
    apiMock.post.mockResolvedValue({ ok: true })
    await authService.verify2FA('123456')
    expect(apiMock.post).toHaveBeenCalledWith(apiEndpoints.auth.verify2FA, { code: '123456' })
  })
})
