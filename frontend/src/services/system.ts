import { api } from './api'
import { apiEndpoints } from './endpoints'

export interface ServerTime {
  timestamp: string
  timezone: string
  epochMs: number
  formatted: string
}

export const systemService = {
  time: () => api.get<ServerTime>(apiEndpoints.system.time),
}

export default systemService
