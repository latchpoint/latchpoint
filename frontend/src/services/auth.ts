import api from './api'
import type { User, LoginCredentials, LoginResponse } from '@/types'
import { apiEndpoints } from './endpoints'

export const authService = {
  async login(credentials: LoginCredentials): Promise<LoginResponse> {
    return api.post<LoginResponse>(apiEndpoints.auth.login, credentials)
  },

  async logout(): Promise<void> {
    await api.post(apiEndpoints.auth.logout)
  },

  async getCurrentUser(): Promise<User> {
    return api.get<User>(apiEndpoints.users.me)
  },

  async verify2FA(code: string): Promise<LoginResponse> {
    return api.post<LoginResponse>(apiEndpoints.auth.verify2FA, { code })
  },
}

export default authService
