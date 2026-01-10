import { Button } from '@/components/ui/button'
import { Tooltip } from '@/components/ui/tooltip'
import { Link } from 'react-router-dom'
import { Routes } from '@/lib/constants'

type Props = {
  isBusy: boolean
  onSyncHaEntities: () => void
  onSyncZwaveEntities: () => void
  onRunRules: () => void
  onRefresh: () => void
}

export function RulesPageActions({
  isBusy,
  onSyncHaEntities,
  onSyncZwaveEntities,
  onRunRules,
  onRefresh,
}: Props) {
  return (
    <>
      <Tooltip content="Imports/updates the local Entity Registry from Home Assistant.">
        <Button type="button" variant="outline" size="sm" onClick={onSyncHaEntities} disabled={isBusy}>
          Sync HA
        </Button>
      </Tooltip>
      <Tooltip content="Imports/updates the local Entity Registry from Z-Wave JS.">
        <Button type="button" variant="outline" size="sm" onClick={onSyncZwaveEntities} disabled={isBusy}>
          Sync Z-Wave
        </Button>
      </Tooltip>
      <Tooltip content="Runs enabled rules immediately using the server-side engine.">
        <Button type="button" variant="outline" size="sm" onClick={onRunRules} disabled={isBusy}>
          Run Rules
        </Button>
      </Tooltip>
      <Button asChild type="button" variant="outline" size="sm">
        <Link to={Routes.RULES_TEST}>Test</Link>
      </Button>
      <Button type="button" variant="outline" size="sm" onClick={onRefresh} disabled={isBusy}>
        Refresh
      </Button>
    </>
  )
}
