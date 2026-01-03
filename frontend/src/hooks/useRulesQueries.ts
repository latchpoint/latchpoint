import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { entitiesService, rulesService } from '@/services'
import type { Rule, RuleDefinition } from '@/types'
import { queryKeys } from '@/types'
import { formatEntitiesSyncNotice, formatRulesRunNotice } from '@/lib/notices'

export function useEntitiesQuery() {
  return useQuery({
    queryKey: queryKeys.entities.all,
    queryFn: entitiesService.list,
  })
}

export function useRulesQuery(params?: { kind?: Rule['kind']; enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.rules.all,
    queryFn: () => rulesService.list(params),
  })
}

export function useSyncEntitiesMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const data = await entitiesService.sync()
      return { data, notice: formatEntitiesSyncNotice(data) }
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.entities.all })
    },
  })
}

export function useRunRulesMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const data = await rulesService.run()
      return { data, notice: formatRulesRunNotice(data) }
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.rules.all })
    },
  })
}

export function useSaveRuleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (vars: {
      id: number | null
      payload: {
        name: string
        kind?: Rule['kind']  // Optional - auto-derived from actions by backend
        enabled: boolean
        priority: number
        schemaVersion: number
        definition: RuleDefinition
        cooldownSeconds?: number | null
        entityIds?: string[]
      }
    }) => {
      const data =
        vars.id == null ? await rulesService.create(vars.payload) : await rulesService.update(vars.id, vars.payload)
      return { data, notice: vars.id == null ? 'Rule created.' : 'Rule updated.' }
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.rules.all })
    },
  })
}

export function useDeleteRuleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => {
      await rulesService.delete(id)
      return { notice: 'Rule deleted.' }
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.rules.all })
    },
  })
}
