import { Button } from '@/components/ui/button'
import { Tooltip } from '@/components/ui/tooltip'
import { Link } from 'react-router-dom'
import { Routes } from '@/lib/constants'

type Props = {
  isSaving: boolean
  onSyncEntities: () => void
  onSyncZwavejsEntities: () => void
  onRunRules: () => void
  onRefresh: () => void
}

export function RulesPageActions({ isSaving, onSyncEntities, onSyncZwavejsEntities, onRunRules, onRefresh }: Props) {
  return (
    <>
      <Tooltip content="Imports/updates the local Entity Registry from Home Assistant, so entity IDs autocomplete and can be referenced in rules.">
        <Button type="button" variant="outline" onClick={onSyncEntities} disabled={isSaving}>
          Sync HA Entities
        </Button>
      </Tooltip>
      <Tooltip content="Imports/updates the local Entity Registry from Z-Wave JS UI / zwave-js-server.">
        <Button type="button" variant="outline" onClick={onSyncZwavejsEntities} disabled={isSaving}>
          Sync Z-Wave Entities
        </Button>
      </Tooltip>
      <Tooltip content="Runs enabled rules immediately using the server-side engine (useful for testing).">
        <Button type="button" variant="outline" onClick={onRunRules} disabled={isSaving}>
          Run Rules
        </Button>
      </Tooltip>
      <Button asChild type="button" variant="outline">
        <Link to={Routes.RULES_TEST}>Test Rules</Link>
      </Button>
      <Button type="button" variant="outline" onClick={onRefresh} disabled={isSaving}>
        Refresh
      </Button>
    </>
  )
}

