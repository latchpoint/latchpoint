import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'
import { apiEndpoints } from '@/services/endpoints'
import { queryKeys } from '@/types'
import type { SettingsRegistryEntry } from '@/types/settingsRegistry'

async function fetchSettingsRegistry(): Promise<SettingsRegistryEntry[]> {
  return api.get<SettingsRegistryEntry[]>(apiEndpoints.alarm.settingsRegistry)
}

export function useSettingsRegistryQuery() {
  return useQuery({
    queryKey: queryKeys.alarm.settingsRegistry,
    queryFn: fetchSettingsRegistry,
    staleTime: 5 * 60 * 1000, // Registry metadata rarely changes
  })
}

export function useSettingsRegistryEntry(key: string) {
  const query = useSettingsRegistryQuery()
  return {
    ...query,
    data: query.data?.find((entry) => entry.key === key) ?? null,
  }
}
