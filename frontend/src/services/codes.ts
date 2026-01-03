import api from './api'
import { apiEndpoints } from './endpoints'
import type {
  AlarmCode,
  CodeUsage,
  CreateCodeRequest,
  UpdateCodeRequest,
  ValidateCodeRequest,
  ValidateCodeResponse,
  PaginatedResponse,
  PaginationParams,
} from '@/types'

export const codesService = {
  async getCodes(params?: { userId?: string }): Promise<AlarmCode[]> {
    return api.get<AlarmCode[]>(apiEndpoints.codes.all, params)
  },

  async getCode(id: number): Promise<AlarmCode> {
    return api.get<AlarmCode>(apiEndpoints.codes.detail(id))
  },

  async createCode(code: CreateCodeRequest): Promise<AlarmCode> {
    return api.post<AlarmCode>(apiEndpoints.codes.all, code)
  },

  async updateCode(id: number, code: UpdateCodeRequest): Promise<AlarmCode> {
    return api.patch<AlarmCode>(apiEndpoints.codes.detail(id), code)
  },

  async deleteCode(id: number): Promise<void> {
    return api.delete(apiEndpoints.codes.detail(id))
  },

  async getCodeUsage(
    id: number,
    params?: PaginationParams
  ): Promise<PaginatedResponse<CodeUsage>> {
    return api.getPaginated<CodeUsage>(apiEndpoints.codes.usage(id), params ? { ...params } : undefined)
  },

  async validateCode(request: ValidateCodeRequest): Promise<ValidateCodeResponse> {
    return api.post<ValidateCodeResponse>(apiEndpoints.auth.validateCode, request)
  },

  async deactivateCode(id: number): Promise<AlarmCode> {
    return api.patch<AlarmCode>(apiEndpoints.codes.detail(id), { isActive: false })
  },

  async activateCode(id: number): Promise<AlarmCode> {
    return api.patch<AlarmCode>(apiEndpoints.codes.detail(id), { isActive: true })
  },
}

export default codesService
