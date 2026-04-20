/**
 * Rule Query Builder component using react-querybuilder
 * Provides a visual interface for building alarm rule conditions
 */
import { useMemo } from 'react'
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
  TimeInRangeValueEditor,
} from './valueEditors'
import type { Entity } from '@/types/rules'
import type { EntitySource, FrigateConfig, ValueEditorContext } from './types'

export type { EntitySource } from './types'


interface RuleQueryBuilderProps {
  query: RuleGroupType
  onQueryChange: (query: RuleGroupType) => void
  entities: Entity[]
  frigateConfig?: FrigateConfig
  disabled?: boolean
}

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
  {
    name: 'time_in_range',
    label: 'Time of day',
    operators: [
      { name: 'between', label: 'is between' },
      { name: '!=', label: 'is NOT between' },
    ],
    defaultOperator: 'between',
  },
]

// Map field names to entity sources for filtering. `Partial` makes the
// lookup honest — only these four keys resolve; any other field yields
// `undefined`, which the `?? 'all'` fallback at the call site handles.
const fieldToSource: Partial<Record<string, EntitySource>> = {
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

// Module-scope dispatcher. Its identity is stable for the lifetime of the app,
// so react-querybuilder never treats it as a "new component type" and never
// unmounts the value-editor instance — local state (e.g. dropdown open/closed)
// survives parent re-renders. Per-render data is forwarded through the
// QueryBuilder `context` prop and arrives here on props.context.
// Exported for a structural regression test (see RuleQueryBuilder.test.tsx)
// that guards against anyone moving this back inside the component body.
export function CustomValueEditor(props: ValueEditorProps) {
  const { field, context } = props
  const editorContext = context as ValueEditorContext | undefined

  if (field === 'alarm_state_in') {
    return <AlarmStateValueEditor {...props} />
  }
  if (field === 'entity_state' || field?.startsWith('entity_state_')) {
    const sourceFilter = fieldToSource[field] ?? 'all'
    return (
      <EntityStateValueEditor
        {...props}
        context={editorContext}
        sourceFilter={sourceFilter}
      />
    )
  }
  if (field === 'frigate_person_detected') {
    return <FrigateValueEditor {...props} context={editorContext} />
  }
  if (field === 'time_in_range') {
    return <TimeInRangeValueEditor {...props} />
  }
  return null
}

const controlElements = { valueEditor: CustomValueEditor }

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

  // Context object passed to value editors via QueryBuilder's `context` prop.
  // Memoised so a single identity is reused across renders whenever the inputs
  // haven't meaningfully changed.
  const context = useMemo<ValueEditorContext>(
    () => ({
      entities: entityOptions,
      frigate: frigateConfig,
    }),
    [entityOptions, frigateConfig]
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
        controlElements={controlElements}
        context={context}
        addRuleToNewGroups
        showCombinatorsBetweenRules={false}
        resetOnFieldChange={false}
        disabled={disabled}
      />
    </div>
  )
}
