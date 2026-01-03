/**
 * Rule Query Builder component using react-querybuilder
 * Provides a visual interface for building alarm rule conditions
 */
import { useMemo, useCallback } from 'react'
import {
  QueryBuilder,
  type RuleGroupType,
  type Field,
  type ValueEditorProps,
} from 'react-querybuilder'
import 'react-querybuilder/dist/query-builder.css'

import { cn } from '@/lib/utils'
import {
  AlarmStateValueEditor,
  EntityStateValueEditor,
  FrigateValueEditor,
} from './valueEditors'
import type { Entity } from '@/types/rules'

interface RuleQueryBuilderProps {
  query: RuleGroupType
  onQueryChange: (query: RuleGroupType) => void
  entities: Entity[]
  frigateConfig?: {
    cameras: string[]
    zonesByCamera: Record<string, string[]>
  }
  disabled?: boolean
}

// Entity sources for filtering
export type EntitySource = 'home_assistant' | 'zwavejs' | 'zigbee2mqtt' | 'all'

// Field definitions for the query builder
const fields: Field[] = [
  {
    name: 'alarm_state_in',
    label: 'Alarm State',
    operators: [
      { name: 'in', label: 'is one of' },
      { name: '!=', label: 'is NOT one of' },
    ],
    defaultOperator: 'in',
  },
  {
    name: 'entity_state',
    label: 'Entity (All Sources)',
    operators: [
      { name: '=', label: 'equals' },
      { name: '!=', label: 'not equals' },
    ],
    defaultOperator: '=',
  },
  {
    name: 'entity_state_ha',
    label: 'Home Assistant Entity',
    operators: [
      { name: '=', label: 'equals' },
      { name: '!=', label: 'not equals' },
    ],
    defaultOperator: '=',
  },
  {
    name: 'entity_state_zwavejs',
    label: 'Z-Wave JS Entity',
    operators: [
      { name: '=', label: 'equals' },
      { name: '!=', label: 'not equals' },
    ],
    defaultOperator: '=',
  },
  {
    name: 'entity_state_z2m',
    label: 'Zigbee2MQTT Entity',
    operators: [
      { name: '=', label: 'equals' },
      { name: '!=', label: 'not equals' },
    ],
    defaultOperator: '=',
  },
  {
    name: 'frigate_person_detected',
    label: 'Frigate Person',
    operators: [
      { name: 'detected', label: 'detected in' },
      { name: '!=', label: 'NOT detected in' },
    ],
    defaultOperator: 'detected',
  },
]

// Map field names to entity sources for filtering
const fieldToSource: Record<string, EntitySource> = {
  entity_state: 'all',
  entity_state_ha: 'home_assistant',
  entity_state_zwavejs: 'zwavejs',
  entity_state_z2m: 'zigbee2mqtt',
}

// Combinators (AND/OR)
const combinators = [
  { name: 'and', label: 'AND' },
  { name: 'or', label: 'OR' },
]

// Translations for the UI
const translations = {
  addRule: { label: '+ Condition', title: 'Add condition' },
  addGroup: { label: '+ Group', title: 'Add group' },
  removeRule: { label: '×', title: 'Remove condition' },
  removeGroup: { label: '×', title: 'Remove group' },
}

export function RuleQueryBuilder({
  query,
  onQueryChange,
  entities,
  frigateConfig,
  disabled = false,
}: RuleQueryBuilderProps) {
  // Prepare entity options for the entity picker (include source for filtering)
  const entityOptions = useMemo(
    () =>
      entities.map((e) => ({
        entityId: e.entityId,
        name: e.name,
        domain: e.domain,
        source: e.source,
      })),
    [entities]
  )

  // Context object passed to value editors
  const context = useMemo(
    () => ({
      entities: entityOptions,
      frigate: frigateConfig,
    }),
    [entityOptions, frigateConfig]
  )

  // Custom value editor that routes to the correct editor based on field
  const CustomValueEditor = useCallback(
    (props: ValueEditorProps) => {
      const { field } = props

      // Handle alarm state
      if (field === 'alarm_state_in') {
        return <AlarmStateValueEditor {...props} context={context} />
      }

      // Handle entity state fields (includes generic 'entity_state' and source-specific fields)
      if (field === 'entity_state' || field?.startsWith('entity_state_')) {
        const sourceFilter = fieldToSource[field] || 'all'
        return <EntityStateValueEditor {...props} context={context} sourceFilter={sourceFilter} />
      }

      // Handle frigate
      if (field === 'frigate_person_detected') {
        return <FrigateValueEditor {...props} context={context} />
      }

      return null
    },
    [context]
  )

  return (
    <div
        className={cn(
          'rule-query-builder',
          // Style the query builder with Tailwind classes
          '[&_.queryBuilder]:space-y-2',
          // Rule groups
          '[&_.ruleGroup]:rounded-lg [&_.ruleGroup]:border [&_.ruleGroup]:border-border [&_.ruleGroup]:bg-card [&_.ruleGroup]:p-3',
          '[&_.ruleGroup-header]:mb-2 [&_.ruleGroup-header]:flex [&_.ruleGroup-header]:flex-wrap [&_.ruleGroup-header]:items-center [&_.ruleGroup-header]:gap-2',
          '[&_.ruleGroup-body]:space-y-2',
          // Nested groups
          '[&_.ruleGroup_.ruleGroup]:ml-4 [&_.ruleGroup_.ruleGroup]:mt-2 [&_.ruleGroup_.ruleGroup]:border-l-2 [&_.ruleGroup_.ruleGroup]:border-l-primary/30',
          // Individual rules
          '[&_.rule]:flex [&_.rule]:flex-wrap [&_.rule]:items-start [&_.rule]:gap-2 [&_.rule]:rounded-md [&_.rule]:border [&_.rule]:border-border [&_.rule]:bg-muted/30 [&_.rule]:p-3',
          // Buttons
          '[&_.ruleGroup-addRule]:rounded-md [&_.ruleGroup-addRule]:border [&_.ruleGroup-addRule]:border-input [&_.ruleGroup-addRule]:bg-background [&_.ruleGroup-addRule]:px-3 [&_.ruleGroup-addRule]:py-1.5 [&_.ruleGroup-addRule]:text-sm [&_.ruleGroup-addRule]:hover:bg-accent',
          '[&_.ruleGroup-addGroup]:rounded-md [&_.ruleGroup-addGroup]:border [&_.ruleGroup-addGroup]:border-input [&_.ruleGroup-addGroup]:bg-background [&_.ruleGroup-addGroup]:px-3 [&_.ruleGroup-addGroup]:py-1.5 [&_.ruleGroup-addGroup]:text-sm [&_.ruleGroup-addGroup]:hover:bg-accent',
          '[&_.rule-remove]:rounded-md [&_.rule-remove]:px-2 [&_.rule-remove]:py-1 [&_.rule-remove]:text-destructive [&_.rule-remove]:hover:bg-destructive/10',
          '[&_.ruleGroup-remove]:rounded-md [&_.ruleGroup-remove]:px-2 [&_.ruleGroup-remove]:py-1 [&_.ruleGroup-remove]:text-destructive [&_.ruleGroup-remove]:hover:bg-destructive/10',
          // Selects
          '[&_.rule-fields]:rounded-md [&_.rule-fields]:border [&_.rule-fields]:border-input [&_.rule-fields]:bg-background [&_.rule-fields]:px-3 [&_.rule-fields]:py-1.5 [&_.rule-fields]:text-sm',
          '[&_.rule-operators]:rounded-md [&_.rule-operators]:border [&_.rule-operators]:border-input [&_.rule-operators]:bg-background [&_.rule-operators]:px-3 [&_.rule-operators]:py-1.5 [&_.rule-operators]:text-sm',
          '[&_.ruleGroup-combinators]:rounded-md [&_.ruleGroup-combinators]:border [&_.ruleGroup-combinators]:border-input [&_.ruleGroup-combinators]:bg-background [&_.ruleGroup-combinators]:px-3 [&_.ruleGroup-combinators]:py-1.5 [&_.ruleGroup-combinators]:text-sm [&_.ruleGroup-combinators]:font-medium',
          // Disabled state
          disabled && 'pointer-events-none opacity-60'
        )}
      >
        <QueryBuilder
        fields={fields}
        query={query}
        onQueryChange={onQueryChange}
        translations={translations}
        combinators={combinators}
        controlElements={{
          valueEditor: CustomValueEditor,
        }}
        addRuleToNewGroups
        showCombinatorsBetweenRules={false}
        resetOnFieldChange={false}
        disabled={disabled}
      />
    </div>
  )
}
