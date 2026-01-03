import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { alarmService, systemConfigService } from '@/services'
import { queryKeys } from '@/types'
import type { AlarmSettingsProfileDetail, AlarmSettingsProfileMeta, SystemConfigRow } from '@/types'
import { useAuthSessionQuery, useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { UserRole } from '@/lib/constants'

function isAdmin(role: string | undefined): boolean {
  return role === UserRole.ADMIN
}

export function useSettingsProfilesQuery() {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  return useQuery({
    queryKey: queryKeys.alarm.settingsProfiles,
    queryFn: alarmService.getSettingsProfiles,
    enabled: isAuthenticated,
  })
}

export function useSettingsProfileDetailQuery(profileId: number | null) {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  return useQuery({
    queryKey: ['alarm', 'settings', 'profiles', 'detail', profileId] as const,
    queryFn: () => alarmService.getSettingsProfile(profileId as number),
    enabled: isAuthenticated && !!profileId,
  })
}

export function useCreateSettingsProfileMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (profile: { name: string }) => alarmService.createSettingsProfile(profile),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.alarm.settingsProfiles })
    },
  })
}

export function useUpdateSettingsProfileMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, changes }: { id: number; changes: { name?: string; entries?: Array<{ key: string; value: unknown }> } }) =>
      alarmService.updateSettingsProfile(id, changes),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.alarm.settingsProfiles })
      await queryClient.invalidateQueries({ queryKey: ['alarm', 'settings', 'profiles', 'detail'] })
      await queryClient.invalidateQueries({ queryKey: queryKeys.alarm.settings })
    },
  })
}

export function useDeleteSettingsProfileMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => alarmService.deleteSettingsProfile(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.alarm.settingsProfiles })
      await queryClient.invalidateQueries({ queryKey: queryKeys.alarm.settings })
    },
  })
}

export function useActivateSettingsProfileMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => alarmService.activateSettingsProfile(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.alarm.settingsProfiles })
      await queryClient.invalidateQueries({ queryKey: queryKeys.alarm.settings })
      await queryClient.invalidateQueries({ queryKey: ['alarm', 'settings', 'profiles', 'detail'] })
    },
  })
}

export function useSystemConfigQuery() {
  const session = useAuthSessionQuery()
  const currentUser = useCurrentUserQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  const isEnabled = isAuthenticated && isAdmin(currentUser.data?.role)
  return useQuery({
    queryKey: queryKeys.systemConfig.all,
    queryFn: systemConfigService.list,
    enabled: isEnabled,
  })
}

export function useUpdateSystemConfigMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ key, changes }: { key: string; changes: { value?: unknown; description?: string } }) =>
      systemConfigService.update(key, changes),
    onSuccess: async (row: SystemConfigRow) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.systemConfig.all })
      await queryClient.setQueryData<SystemConfigRow[] | undefined>(queryKeys.systemConfig.all, (prev) => {
        if (!prev) return prev
        return prev.map((r) => (r.key === row.key ? row : r))
      })
    },
  })
}

export type { AlarmSettingsProfileMeta, AlarmSettingsProfileDetail }
