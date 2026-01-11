/**
 * Rule Builder - Complete rule builder using React Query Builder
 * Combines metadata, conditions (via RQB), and actions into a single form
 * Note: 'kind' is auto-derived from actions by the backend
 */
import { useState, useCallback, useMemo } from 'react'
import type { RuleGroupType } from 'react-querybuilder'
import type { Rule, Entity } from '@/types/rules'
import type { ActionNode, RuleDefinition, WhenNode } from '@/types/ruleDefinition'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { HelpTip } from '@/components/ui/help-tip'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { RuleQueryBuilder } from './RuleQueryBuilder'
import { ActionsEditor } from './ActionsEditor'
import { alarmDslToRqbWithFor, rqbToAlarmDsl, createEmptyQuery } from './converters'

interface RuleBuilderProps {
  rule?: Rule | null
  entities: Entity[]
  frigateConfig?: {
    cameras: string[]
    zonesByCamera: Record<string, string[]>
  }
  onSave: (payload: {
    name: string
    enabled: boolean
    priority: number
    schemaVersion: number
    definition: RuleDefinition
    cooldownSeconds?: number | null
    entityIds?: string[]
  }) => void
  onCancel: () => void
  onDelete?: () => void
  isSaving: boolean
}

export function RuleBuilder({
  rule,
  entities,
  frigateConfig,
  onSave,
  onCancel,
  onDelete,
  isSaving,
}: RuleBuilderProps) {
  // Form state (kind is auto-derived from actions by backend)
  const [name, setName] = useState(rule?.name || '')
  const [enabled, setEnabled] = useState(rule?.enabled ?? true)
  const [priority, setPriority] = useState(rule?.priority ?? 100)
  const [cooldownSeconds, setCooldownSeconds] = useState<string>(
    rule?.cooldownSeconds?.toString() || ''
  )

  // Advanced mode state
  const [advanced, setAdvanced] = useState(false)
  const [definitionText, setDefinitionText] = useState('')
  const [jsonError, setJsonError] = useState<string | null>(null)

  // Condition state (RQB format) and forSeconds
  // Pass entities to converter for source lookup
  const [query, setQuery] = useState<RuleGroupType>(() => {
    if (rule?.definition?.when) {
      return alarmDslToRqbWithFor(rule.definition.when, entities).query
    }
    return createEmptyQuery()
  })

  const [forSeconds, setForSeconds] = useState<string>(() => {
    if (rule?.definition?.when) {
      const result = alarmDslToRqbWithFor(rule.definition.when, entities)
      return result.forSeconds?.toString() || ''
    }
    return ''
  })

  // Actions state
  const [actions, setActions] = useState<ActionNode[]>(() => {
    return rule?.definition?.then || [{ type: 'alarm_trigger' }]
  })

  // Parse forSeconds to number
  const forSecondsNum = useMemo(() => {
    const parsed = parseInt(forSeconds, 10)
    return isNaN(parsed) || parsed <= 0 ? null : parsed
  }, [forSeconds])

  // Compute the builder's current definition as JSON text (for display in advanced mode)
  const builderDefinitionText = useMemo(() => {
    const whenNode = rqbToAlarmDsl(query, forSecondsNum)
    const definition: RuleDefinition = {
      when: whenNode,
      then: actions,
    }
    return JSON.stringify(definition, null, 2)
  }, [query, actions, forSecondsNum])

  const builderGuardrailError = useMemo(() => {
    if (!query?.rules?.length) return null

    let hasTime = false
    let hasTriggerable = false

    const walk = (group: RuleGroupType) => {
      for (const r of group.rules) {
        if ('combinator' in r) {
          walk(r as RuleGroupType)
          continue
        }
        const field = (r as any).field as string | undefined
        if (!field) continue
        if (field === 'time_in_range') hasTime = true
        else hasTriggerable = true
      }
    }

    walk(query)
    if (hasTime && !hasTriggerable) {
      return 'Time of day must be combined with at least one entity/alarm/Frigate condition (time-only rules do not fire yet).'
    }
    return null
  }, [query])

  // Handle toggling between builder and advanced modes
  const handleToggleAdvanced = useCallback(() => {
    setAdvanced((prev) => {
      const next = !prev
      if (next) {
        // Entering advanced mode: copy current builder state to JSON textarea
        setDefinitionText(builderDefinitionText)
        setJsonError(null)
      } else {
        // Exiting advanced mode: try to parse JSON and update builder state
        try {
          const parsed = JSON.parse(definitionText) as RuleDefinition
          if (parsed.when) {
            const result = alarmDslToRqbWithFor(parsed.when, entities)
            setQuery(result.query)
            setForSeconds(result.forSeconds?.toString() || '')
          }
          if (parsed.then) {
            setActions(parsed.then)
          }
          setJsonError(null)
        } catch {
          // If JSON is invalid, keep advanced mode and show error
          setJsonError('Invalid JSON. Fix errors before switching to builder mode.')
          return true // Stay in advanced mode
        }
      }
      return next
    })
  }, [builderDefinitionText, definitionText, entities])

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()

      let definition: RuleDefinition

      if (advanced) {
        // In advanced mode, use the JSON from the textarea
        try {
          definition = JSON.parse(definitionText) as RuleDefinition
          setJsonError(null)
        } catch {
          setJsonError('Invalid JSON. Cannot save.')
          return
        }
      } else {
        if (builderGuardrailError) {
          return
        }
        // In builder mode, convert RQB query to our DSL
        const whenNode = rqbToAlarmDsl(query, forSecondsNum) as WhenNode
        definition = {
          when: whenNode,
          then: actions,
        }
      }

      onSave({
        name: name.trim() || 'Untitled Rule',
        enabled,
        priority,
        schemaVersion: 1,
        definition,
        cooldownSeconds: cooldownSeconds ? parseInt(cooldownSeconds, 10) : null,
      })
    },
    [query, actions, name, enabled, priority, cooldownSeconds, onSave, advanced, definitionText, forSecondsNum, builderGuardrailError]
  )

  const isEditing = rule?.id != null

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Rule Metadata */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {isEditing ? 'Edit Rule' : 'New Rule'}
          </CardTitle>
          <CardDescription>
            Configure the rule's basic settings
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <FormField label="Name" htmlFor="rule-name" required>
              <Input
                id="rule-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Motion triggers alarm"
                disabled={isSaving}
              />
            </FormField>

            <FormField
              label="Priority"
              htmlFor="rule-priority"
              help="Higher priority rules are evaluated first"
            >
              <Input
                id="rule-priority"
                type="number"
                min={0}
                max={1000}
                value={priority}
                onChange={(e) => setPriority(parseInt(e.target.value) || 100)}
                disabled={isSaving}
              />
            </FormField>

            <FormField
              label="Cooldown (sec)"
              htmlFor="rule-cooldown"
              help="Prevents rule from firing again within this time"
            >
              <Input
                id="rule-cooldown"
                type="number"
                min={0}
                value={cooldownSeconds}
                onChange={(e) => setCooldownSeconds(e.target.value)}
                placeholder="Optional"
                disabled={isSaving}
              />
            </FormField>
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Switch
                id="rule-enabled"
                checked={enabled}
                onCheckedChange={setEnabled}
                disabled={isSaving}
              />
              <label htmlFor="rule-enabled" className="text-sm">
                Rule enabled
              </label>
            </div>

            <Button
              type="button"
              variant={advanced ? 'default' : 'outline'}
              size="sm"
              onClick={handleToggleAdvanced}
              disabled={isSaving}
            >
              {advanced ? 'Builder Mode' : 'Advanced JSON'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Visual Builder - Only shown in builder mode */}
      {!advanced && (
        <>
          {/* Conditions (WHEN) */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                When{' '}
                <HelpTip
                  className="ml-1"
                  content="Conditions that must be met for the rule to fire. Use AND to require all conditions, OR to require any."
                />
              </CardTitle>
              <CardDescription>
                Define the conditions that trigger this rule
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* For seconds duration */}
              <div className="flex items-center gap-3 rounded-md border bg-muted/30 p-3">
                <FormField
                  label="For duration (seconds)"
                  htmlFor="for-seconds"
                  help="Require conditions to remain true for this many seconds before firing"
                  className="flex-1"
                >
                  <Input
                    id="for-seconds"
                    type="number"
                    min={0}
                    value={forSeconds}
                    onChange={(e) => setForSeconds(e.target.value)}
                    placeholder="Optional (e.g., 300 for 5 min)"
                    disabled={isSaving}
                    className="max-w-[250px]"
                  />
                </FormField>
                {forSecondsNum && forSecondsNum > 0 && (
                  <span className="text-sm text-muted-foreground">
                    = {Math.floor(forSecondsNum / 60)}m {forSecondsNum % 60}s
                  </span>
                )}
              </div>

              <RuleQueryBuilder
                query={query}
                onQueryChange={setQuery}
                entities={entities}
                frigateConfig={frigateConfig}
                disabled={isSaving}
              />
              {builderGuardrailError && (
                <p className="text-sm text-destructive">{builderGuardrailError}</p>
              )}
            </CardContent>
          </Card>

          {/* Actions (THEN) */}
          <ActionsEditor actions={actions} onChange={setActions} disabled={isSaving} />
        </>
      )}

      {/* JSON Definition - Only shown in advanced mode */}
      {advanced && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Definition (JSON){' '}
              <HelpTip
                className="ml-1"
                content="Edit the rule definition directly as JSON"
              />
            </CardTitle>
            <CardDescription>
              Edit the rule definition directly as JSON
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Textarea
              className="min-h-[220px] font-mono text-xs"
              value={definitionText}
              onChange={(e) => setDefinitionText(e.target.value)}
              spellCheck={false}
              disabled={isSaving}
            />
            {jsonError && (
              <p className="text-sm text-destructive">{jsonError}</p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Form Actions */}
      <Card>
        <CardContent className="flex items-center justify-between gap-4 pt-6">
          <div>
            {isEditing && onDelete && (
              <Button
                type="button"
                variant="destructive"
                onClick={onDelete}
                disabled={isSaving}
              >
                Delete Rule
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={onCancel} disabled={isSaving}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSaving || (!advanced && !!builderGuardrailError)}>
              {isSaving ? 'Saving...' : isEditing ? 'Update Rule' : 'Create Rule'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </form>
  )
}
