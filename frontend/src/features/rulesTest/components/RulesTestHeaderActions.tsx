import { Button } from '@/components/ui/button'
import { Tooltip } from '@/components/ui/tooltip'
import { Link } from 'react-router-dom'
import { Routes } from '@/lib/constants'

type Props = {
  onSyncHa: () => void
  onSyncZwave: () => void
  onRefreshEntities: () => void
  disabled: boolean
}

export function RulesTestHeaderActions({ onSyncHa, onSyncZwave, onRefreshEntities, disabled }: Props) {
  return (
    <>
      <Button asChild variant="outline">
        <Link to={Routes.RULES}>Back to Rules</Link>
      </Button>
      <Tooltip content="Imports/updates the local Entity Registry from Home Assistant.">
        <Button type="button" variant="outline" onClick={onSyncHa} disabled={disabled}>
          Sync HA Entities
        </Button>
      </Tooltip>
      <Tooltip content="Imports/updates the local Entity Registry from Z-Wave JS UI / zwave-js-server.">
        <Button type="button" variant="outline" onClick={onSyncZwave} disabled={disabled}>
          Sync Z-Wave Entities
        </Button>
      </Tooltip>
      <Button type="button" variant="outline" onClick={onRefreshEntities} disabled={disabled}>
        Refresh
      </Button>
    </>
  )
}

