/**
 * Rules Page - Visual rule builder using React Query Builder
 */
import { useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Copy } from 'lucide-react'
import { Page } from '@/components/layout'
import { Spinner } from '@/components/ui/spinner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { RuleBuilder, RulesPageActions, cloneRule } from '@/features/rules/queryBuilder'
import type { RuleSeed } from '@/features/rules/queryBuilder'
import { RulesPageNotices } from '@/features/rules/components/RulesPageNotices'
import {
  useRulesQuery,
  useEntitiesQuery,
  useSaveRuleMutation,
  useDeleteRuleMutation,
  useSyncEntitiesMutation,
  useRunRulesMutation,
} from '@/hooks/useRulesQueries'
import { useSyncZwavejsEntitiesMutation } from '@/hooks/useZwavejs'
import { queryKeys } from '@/types'
import { getErrorMessage } from '@/types/errors'
import type { Entity, Rule } from '@/types/rules'
import type { RuleDefinition } from '@/types/ruleDefinition'

// Stable empty-array reference so downstream memos (entityOptions, context, …)
// don't invalidate every render while the entities query resolves.
const EMPTY_ENTITIES: Entity[] = []

export function RulesPage() {
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const editId = searchParams.get('edit')

  // Notice and error state for inline display
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const { data: rules, isLoading: rulesLoading, error: rulesError } = useRulesQuery()
  const { data: entities, isLoading: entitiesLoading, error: entitiesError } = useEntitiesQuery()
  const saveMutation = useSaveRuleMutation()
  const deleteMutation = useDeleteRuleMutation()
  const syncHaMutation = useSyncEntitiesMutation()
  const syncZwaveMutation = useSyncZwavejsEntitiesMutation()
  const runRulesMutation = useRunRulesMutation()

  const [selectedRuleId, setSelectedRuleId] = useState<number | null>(
    editId ? parseInt(editId, 10) : null
  )
  const [seed, setSeed] = useState<RuleSeed | null>(null)
  const [builderNonce, setBuilderNonce] = useState(0)

  const selectedRule = rules?.find((r) => r.id === selectedRuleId) || null
  const isLoading = rulesLoading || entitiesLoading
  const isSaving = saveMutation.isPending || deleteMutation.isPending
  const isBusy =
    isSaving ||
    syncHaMutation.isPending ||
    syncZwaveMutation.isPending ||
    runRulesMutation.isPending

  // Combine errors from queries
  const displayedError = error || getErrorMessage(rulesError) || getErrorMessage(entitiesError) || null

  const handleSave = useCallback(
    async (payload: {
      name: string
      enabled: boolean
      priority: number
      stopProcessing: boolean
      stopGroup: string
      schemaVersion: number
      definition: RuleDefinition
      cooldownSeconds?: number | null
      entityIds?: string[]
    }) => {
      setNotice(null)
      setError(null)
      try {
        const result = await saveMutation.mutateAsync({
          id: selectedRuleId,
          payload,
        })
        setNotice(result.notice)
        setSelectedRuleId(null)
        setSeed(null)
        setBuilderNonce((n) => n + 1)
      } catch (err) {
        setError(getErrorMessage(err) || 'Failed to save rule')
      }
    },
    [saveMutation, selectedRuleId]
  )

  const handleDelete = useCallback(async () => {
    if (!selectedRuleId) return
    if (!confirm('Are you sure you want to delete this rule?')) return

    setNotice(null)
    setError(null)
    try {
      const result = await deleteMutation.mutateAsync(selectedRuleId)
      setNotice(result.notice)
      setSelectedRuleId(null)
      setSeed(null)
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to delete rule')
    }
  }, [deleteMutation, selectedRuleId])

  const handleCancel = useCallback(() => {
    setSelectedRuleId(null)
    setSeed(null)
    setBuilderNonce((n) => n + 1)
  }, [])

  const handleNewRule = useCallback(() => {
    setSelectedRuleId(null)
    setSeed(null)
    setBuilderNonce((n) => n + 1)
  }, [])

  const handleEditRule = useCallback((rule: Rule) => {
    setSelectedRuleId(rule.id)
    setSeed(null)
  }, [])

  const handleCopyRule = useCallback(
    (rule: Rule) => {
      if (!confirm(`Copy rule "${rule.name}"?`)) return
      const existingNames = rules?.map((r) => r.name) ?? []
      const nextSeed = cloneRule(rule, existingNames)
      setSelectedRuleId(null)
      setSeed(nextSeed)
      setBuilderNonce((n) => n + 1)
    },
    [rules]
  )

  const handleSyncHaEntities = useCallback(async () => {
    setNotice(null)
    setError(null)
    try {
      const result = await syncHaMutation.mutateAsync()
      setNotice(result.notice)
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to sync HA entities')
    }
  }, [syncHaMutation])

  const handleSyncZwaveEntities = useCallback(async () => {
    setNotice(null)
    setError(null)
    try {
      const result = await syncZwaveMutation.mutateAsync()
      setNotice(result.notice)
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to sync Z-Wave entities')
    }
  }, [syncZwaveMutation])

  const handleRunRules = useCallback(async () => {
    setNotice(null)
    setError(null)
    try {
      const result = await runRulesMutation.mutateAsync()
      setNotice(result.notice)
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to run rules')
    }
  }, [runRulesMutation])

  const handleRefresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.rules.all })
    void queryClient.invalidateQueries({ queryKey: queryKeys.entities.all })
  }, [queryClient])

  if (isLoading) {
    return (
      <Page title="Rule Builder" description="Loading...">
        <Spinner size="lg" />
      </Page>
    )
  }

  // Show rule builder form
  const showBuilder = selectedRuleId !== null || selectedRuleId === null

  return (
    <Page
      title="Rule Builder"
      description="Create and edit alarm rules with a visual interface"
      actions={
        <div className="flex flex-wrap gap-2">
          <RulesPageActions
            isBusy={isBusy}
            onSyncHaEntities={() => void handleSyncHaEntities()}
            onSyncZwaveEntities={() => void handleSyncZwaveEntities()}
            onRunRules={() => void handleRunRules()}
            onRefresh={handleRefresh}
          />
        </div>
      }
    >
      <RulesPageNotices notice={notice} error={displayedError} />

      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        {/* Rules List Sidebar */}
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">Rules</CardTitle>
            <CardDescription>Select a rule to edit or create new</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Button
              variant={selectedRuleId === null ? 'default' : 'outline'}
              className="w-full justify-start"
              onClick={handleNewRule}
            >
              + New Rule
            </Button>

            {rules && rules.length > 0 && (
              <div className="space-y-1 pt-2">
                {rules.map((rule) => {
                  const isSelected = selectedRuleId === rule.id
                  const mutedClass = isSelected
                    ? 'text-primary-foreground/70'
                    : 'text-muted-foreground'
                  return (
                    <div
                      key={rule.id}
                      className={`flex items-stretch gap-1 rounded-md transition-colors ${
                        isSelected ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => handleEditRule(rule)}
                        className="flex-1 rounded-l-md px-3 py-2 text-left text-sm"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-medium">{rule.name}</span>
                          <span className={`text-xs ${mutedClass}`}>{rule.kind}</span>
                        </div>
                        <div className={`text-xs ${mutedClass}`}>
                          {rule.enabled ? 'Enabled' : 'Disabled'} • Priority {rule.priority}
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleCopyRule(rule)}
                        aria-label={`Copy rule ${rule.name}`}
                        title="Copy rule"
                        disabled={isBusy}
                        className={`flex items-center justify-center rounded-r-md px-2 text-sm transition-colors ${
                          isSelected
                            ? 'hover:bg-primary-foreground/10'
                            : 'hover:bg-muted-foreground/10'
                        } disabled:cursor-not-allowed disabled:opacity-50`}
                      >
                        <Copy className="h-4 w-4" aria-hidden="true" />
                      </button>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Rule Builder */}
        <div>
          {showBuilder && (
            <RuleBuilder
              key={`${selectedRuleId ?? (seed ? 'copy' : 'new')}-${builderNonce}`}
              rule={selectedRule}
              seed={selectedRule ? null : seed}
              entities={entities ?? EMPTY_ENTITIES}
              onSave={handleSave}
              onCancel={handleCancel}
              onDelete={selectedRule ? handleDelete : undefined}
              isSaving={isSaving}
            />
          )}
        </div>
      </div>
    </Page>
  )
}

export default RulesPage
