import { api } from './api'
import { apiEndpoints } from './endpoints'

export interface OnboardingStatus {
  onboardingRequired: boolean
}

export interface SetupStatus {
  onboardingRequired: boolean
  setupRequired: boolean
  requirements: {
    hasActiveSettingsProfile: boolean
    hasAlarmSnapshot: boolean
    hasAlarmCode: boolean
    hasSensors: boolean
    homeAssistantConnected: boolean
  }
}

export interface OnboardingRequest {
  email: string
  password: string
}

export interface OnboardingResponse {
  userId: string
  email: string
}

export const onboardingService = {
  async status(): Promise<OnboardingStatus> {
    return api.get<OnboardingStatus>(apiEndpoints.onboarding.base)
  },

  async create(payload: OnboardingRequest): Promise<OnboardingResponse> {
    return api.post<OnboardingResponse>(apiEndpoints.onboarding.base, payload)
  },

  async setupStatus(): Promise<SetupStatus> {
    return api.get<SetupStatus>(apiEndpoints.onboarding.setupStatus)
  },
}

export default onboardingService
