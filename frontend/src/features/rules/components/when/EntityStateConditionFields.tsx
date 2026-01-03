import { DatalistInput } from '@/components/ui/datalist-input'
import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import type { EntityStateConditionRow } from '@/features/rules/builder'

type Props = {
  row: EntityStateConditionRow
  isSaving: boolean
  entityIdOptions: string[]
  entityIdSet: Set<string>
  entitiesLength: number
  onChange: (next: EntityStateConditionRow) => void
}

export function EntityStateConditionFields({ row, isSaving, entityIdOptions, entityIdSet, entitiesLength, onChange }: Props) {
  return (
    <div className="grid items-end gap-2 md:grid-cols-12">
      <div className="space-y-1 md:col-span-6">
        <label className="text-xs text-muted-foreground">
          Entity ID{' '}
          <HelpTip
            className="ml-1"
            content="An entity_id like binary_sensor.front_door or zwavejs:... Use Sync buttons at the top to import entities."
          />
        </label>
        <DatalistInput
          listId="entity-id-options"
          options={entityIdOptions}
          value={row.entityId}
          onChange={(e) => onChange({ ...row, entityId: e.target.value })}
          placeholder="binary_sensor.front_door"
          disabled={isSaving}
        />
      </div>
      <div className="space-y-1 md:col-span-4">
        <label className="text-xs text-muted-foreground">
          Equals{' '}
          <HelpTip
            className="ml-1"
            content="The expected state string. Common examples: on/off, open/closed, locked/unlocked."
          />
        </label>
        <Input value={row.equals} onChange={(e) => onChange({ ...row, equals: e.target.value })} disabled={isSaving} />
      </div>
      {row.entityId.trim() && entitiesLength > 0 && !entityIdSet.has(row.entityId.trim()) ? (
        <div className="text-xs text-muted-foreground md:col-span-12">
          Unknown entity: {row.entityId.trim()} (sync entities or check spelling)
        </div>
      ) : null}
    </div>
  )
}

