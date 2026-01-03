import api from './api'
import type { User } from '@/types'
import { apiEndpoints } from './endpoints'

export const usersService = {
  async listUsers(): Promise<User[]> {
    return api.get<User[]>(apiEndpoints.users.all)
  },
}

export default usersService
