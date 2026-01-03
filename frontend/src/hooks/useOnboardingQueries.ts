import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { onboardingService } from '@/services'
import type { OnboardingRequest } from '@/services/onboarding'
import { queryKeys } from '@/types'
import { useAuthSessionQuery } from '@/hooks/useAuthQueries'

export function useOnboardingStatusQuery() {
  return useQuery({
    queryKey: queryKeys.onboarding.status,
    queryFn: onboardingService.status,
  })
}

export function useSetupStatusQuery() {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  return useQuery({
    queryKey: queryKeys.onboarding.setupStatus,
    queryFn: onboardingService.setupStatus,
    enabled: isAuthenticated,
  })
}

export function useOnboardingCreateMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: OnboardingRequest) => onboardingService.create(payload),
    onSuccess: async () => {
      queryClient.setQueryData(queryKeys.onboarding.status, { onboardingRequired: false })
      await queryClient.invalidateQueries({ queryKey: queryKeys.onboarding.status })
    },
  })
}
