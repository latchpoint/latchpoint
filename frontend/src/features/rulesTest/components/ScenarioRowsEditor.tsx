import type { Dispatch, SetStateAction } from 'react'

import { Button } from '@/components/ui/button'
import { DatalistInput } from '@/components/ui/datalist-input'
import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'

type Props<Row, Entity> = {
  rows: Row[]
  setRows: Dispatch<SetStateAction<Row[]>>
  entityIdOptions: string[]
  entitiesById: Map<string, Entity>
  setRowEntityId: (rowId: string, nextEntityId: string) => void
  isLoading: boolean
  isRunning: boolean
}

export function ScenarioRowsEditor<Row extends { id: string; entityId: string; state: string }, Entity extends { lastState?: unknown }>(
  props: Props<Row, Entity>
) {
  const { rows, setRows, entityIdOptions, entitiesById, setRowEntityId, isLoading, isRunning } = props

  return (
    <>
      {rows.map((row) => (
        <div key={row.id} className="grid items-end gap-2 md:grid-cols-12">
          <div className="space-y-1 md:col-span-7">
            <label className="text-xs text-muted-foreground">
              Entity ID{' '}
              <HelpTip
                className="ml-1"
                content="Pick a Home Assistant entity_id. Use “Sync Entities” at the top if the list is empty."
              />
            </label>
            <DatalistInput
              listId="rules-test-entity-options"
              options={entityIdOptions}
              maxOptions={500}
              value={row.entityId}
              onChange={(e) => {
                setRowEntityId(row.id, e.target.value)
              }}
              placeholder="binary_sensor.front_door"
              disabled={isLoading || isRunning}
            />
            {row.entityId.trim() && entitiesById.get(row.entityId.trim())?.lastState != null ? (
              <div className="text-xs text-muted-foreground">
                Baseline: {String(entitiesById.get(row.entityId.trim())?.lastState)}
              </div>
            ) : null}
          </div>

          <div className="space-y-1 md:col-span-3">
            <label className="text-xs text-muted-foreground">
              State <HelpTip className="ml-1" content="The simulated state string for this entity (e.g., on/off/open/closed)." />
            </label>
            <Input
              value={row.state}
              onChange={(e) => {
                const value = e.target.value
                setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, state: value } : r)))
              }}
              placeholder="on"
              disabled={isLoading || isRunning}
            />
            <div className="flex flex-wrap gap-1 pt-1">
              {['on', 'off', 'open', 'closed', 'locked', 'unlocked'].map((v) => (
                <button
                  key={v}
                  type="button"
                  className="rounded border border-input bg-background px-2 py-0.5 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                  disabled={isRunning}
                  onClick={() => setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, state: v } : r)))}
                >
                  {v}
                </button>
              ))}
            </div>
          </div>

          <div className="flex justify-end gap-2 md:col-span-2">
            <Button
              type="button"
              variant="outline"
              disabled={rows.length <= 1 || isRunning}
              onClick={() => setRows((prev) => prev.filter((r) => r.id !== row.id))}
            >
              Remove
            </Button>
          </div>
        </div>
      ))}
    </>
  )
}

