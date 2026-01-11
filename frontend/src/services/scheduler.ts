import type { PaginatedResponse, SchedulerStatusResponse, SchedulerTaskRun } from '@/types'

import api from './api'
import { apiEndpoints } from './endpoints'

export const schedulerService = {
  getStatus: async (params?: { instanceId?: string }): Promise<SchedulerStatusResponse> => {
    return api.get<SchedulerStatusResponse>(apiEndpoints.scheduler.status, params)
  },

  getTaskRuns: async (
    taskName: string,
    params?: {
      page?: number
      pageSize?: number
      instanceId?: string
      status?: string
      since?: string
    }
  ): Promise<PaginatedResponse<SchedulerTaskRun>> => {
    return api.getPaginated<SchedulerTaskRun>(apiEndpoints.scheduler.taskRuns(taskName), params)
  },
}

