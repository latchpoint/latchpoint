import { Button } from '@/components/ui/button'
import { DatalistInput } from '@/components/ui/datalist-input'
import { HelpTip } from '@/components/ui/help-tip'
import { IconButton } from '@/components/ui/icon-button'
import { X } from 'lucide-react'
import { parseEntityIds, uniqueStrings } from '@/features/rules/builder'

type Props = {
  actionId: string
  targetEntityIdsText: string
  entityIdOptions: string[]
  isSaving: boolean
  pickerValue: string
  setPickerValue: (next: string) => void
  updateHaActionTargetEntityIds: (actionId: string, nextEntityIds: string[]) => void
}

export function HaTargetEntityIdsPicker({
  actionId,
  targetEntityIdsText,
  entityIdOptions,
  isSaving,
  pickerValue,
  setPickerValue,
  updateHaActionTargetEntityIds,
}: Props) {
  const selected = parseEntityIds(targetEntityIdsText)

  const addSelected = () => {
    const next = pickerValue.trim()
    if (!next) return
    updateHaActionTargetEntityIds(actionId, [...selected, next])
    setPickerValue('')
  }

  const removeSelected = (entityId: string) => {
    updateHaActionTargetEntityIds(
      actionId,
      selected.filter((id) => id !== entityId)
    )
  }

  return (
    <div className="space-y-1 md:col-span-3">
      <label className="text-xs text-muted-foreground">
        Target entity IDs <HelpTip className="ml-1" content="Select one or more entity_ids to target (maps to target.entity_ids)." />
      </label>
      <div className="space-y-2">
        <div className="flex flex-col gap-2 md:flex-row">
          <div className="flex-1">
            <DatalistInput
              listId={`ha-target-entities-${actionId}`}
              options={entityIdOptions}
              value={pickerValue}
              onChange={(e) => setPickerValue(e.target.value)}
              placeholder="light.kitchen"
              disabled={isSaving}
            />
          </div>
          <Button type="button" variant="outline" onClick={addSelected} disabled={isSaving}>
            Add
          </Button>
        </div>

        {selected.length ? (
          <div className="flex flex-wrap gap-1">
            {uniqueStrings(selected).map((entityId) => (
              <span key={entityId} className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-1 text-xs">
                {entityId}
                <IconButton type="button" variant="ghost" aria-label={`Remove ${entityId}`} onClick={() => removeSelected(entityId)}>
                  <X className="h-3 w-3" />
                </IconButton>
              </span>
            ))}
          </div>
        ) : (
          <div className="text-xs text-muted-foreground">No entities selected.</div>
        )}
      </div>
    </div>
  )
}

