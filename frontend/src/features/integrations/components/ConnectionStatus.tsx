import { Pill } from '@/components/ui/pill'

type Props = {
  connected?: boolean
  enabled?: boolean
  lastError?: string | null
}

type Labels = {
  connected?: string
  disconnected?: string
  disabled?: string
}

function getConnectionDisplay(
  { connected, enabled }: Pick<Props, 'connected' | 'enabled'>,
  labels?: Labels
): {
  label: string
  className: string
} {
  if (connected) return { label: labels?.connected ?? 'Connected', className: 'text-success' }
  if (enabled === false) return { label: labels?.disabled ?? 'Disabled', className: 'text-muted-foreground' }
  if (enabled === true) return { label: labels?.disconnected ?? 'Disconnected', className: 'text-warning' }
  return { label: labels?.disconnected ?? 'Disconnected', className: 'text-muted-foreground' }
}

export function ConnectionPill({ connected, enabled, labels }: Props & { labels?: Labels }) {
  const display = getConnectionDisplay({ connected, enabled }, labels)
  return <Pill className={display.className}>{display.label}</Pill>
}

export function ConnectionStatusPills({ connected, enabled, lastError, labels }: Props & { labels?: Labels }) {
  const display = getConnectionDisplay({ connected, enabled }, labels)
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-muted-foreground">Status:</span>
      <Pill className={display.className}>{display.label}</Pill>
      {lastError ? <span className="text-muted-foreground">({lastError})</span> : null}
    </div>
  )
}

export function ConnectionStatusTextBlock({ connected, enabled, lastError }: Props) {
  const display = getConnectionDisplay({ connected, enabled })
  return (
    <div className="space-y-2 text-sm">
      <div>
        Status: <span className={`font-medium ${display.className}`}>{display.label}</span>
      </div>
      {lastError ? <div className="text-muted-foreground">Last error: {lastError}</div> : null}
    </div>
  )
}
