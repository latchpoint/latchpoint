import { Children, cloneElement, isValidElement, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { HelpTip } from '@/components/ui/help-tip'
import { Pill } from '@/components/ui/pill'
import { SectionCard } from '@/components/ui/section-card'
import { Switch } from '@/components/ui/switch'
import { ConnectionPill } from '@/features/integrations/components/ConnectionStatus'
import { cn } from '@/lib/utils'

type Status = {
  connected: boolean | undefined
  enabled: boolean | undefined
  lastError?: string | null | undefined
  labels?: Parameters<typeof ConnectionPill>[0]['labels']
}

type Props = {
  title: ReactNode
  description?: ReactNode

  isAdmin: boolean
  isBusy: boolean

  status?: Status
  statusExtra?: ReactNode

  enableLabel?: ReactNode
  enableHelp?: string
  enabled?: boolean
  onEnabledChange?: (enabled: boolean) => void
  enableDisabled?: boolean

  onRefresh?: () => void
  onReset?: () => void
  onSave?: () => void
  resetDisabled?: boolean
  saveDisabled?: boolean

  opsActions?: ReactNode
  children?: ReactNode
}

export function IntegrationOverviewCard({
  title,
  description,
  isAdmin,
  isBusy,
  status,
  statusExtra,
  enableLabel = 'Enable',
  enableHelp,
  enabled,
  onEnabledChange,
  enableDisabled,
  onRefresh,
  onReset,
  onSave,
  resetDisabled,
  saveDisabled,
  opsActions,
  children,
}: Props) {
  const canToggle = Boolean(onEnabledChange) && typeof enabled === 'boolean'

  const makeActionResponsive = (node: ReactNode) => {
    if (!isValidElement(node)) return node
    const props = node.props as Record<string, unknown>
    if (!('className' in props)) return node
    return cloneElement(node, { className: cn(props.className as string | undefined, 'w-full sm:w-auto') } as never)
  }

  const ops = opsActions ? Children.toArray(opsActions).map(makeActionResponsive) : null

  return (
    <SectionCard
      title={title}
      description={description}
      actions={
        onRefresh || onReset || onSave || opsActions ? (
          <div className="flex flex-col gap-1.5 sm:flex-row sm:flex-wrap sm:justify-end sm:gap-2">
            {onRefresh ? (
              <Button type="button" variant="outline" onClick={onRefresh} disabled={isBusy} className="w-full sm:w-auto">
                Refresh
              </Button>
            ) : null}
            {onReset ? (
              <Button
                type="button"
                variant="secondary"
                onClick={onReset}
                disabled={isBusy || Boolean(resetDisabled) || !isAdmin}
                className="w-full sm:w-auto"
              >
                Reset
              </Button>
            ) : null}
            {onSave ? (
              <Button type="button" onClick={onSave} disabled={isBusy || Boolean(saveDisabled) || !isAdmin} className="w-full sm:w-auto">
                Save
              </Button>
            ) : null}
            {ops}
          </div>
        ) : undefined
      }
    >
      <div className="space-y-2 sm:space-y-3">
        {status ? (
          <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
            <ConnectionPill connected={status.connected} enabled={status.enabled} labels={status.labels} />
            {status.lastError ? <Pill className="text-destructive">{status.lastError}</Pill> : null}
            {statusExtra}
          </div>
        ) : statusExtra ? (
          <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">{statusExtra}</div>
        ) : null}

        {canToggle ? (
          <div className="flex items-center justify-between gap-2 sm:gap-4">
            <div className="flex items-center gap-1.5 text-sm font-medium sm:gap-2">
              <span>{enableLabel}</span>
              {enableHelp ? <HelpTip content={enableHelp} /> : null}
            </div>
            <Switch checked={enabled} onCheckedChange={onEnabledChange} disabled={!isAdmin || isBusy || enableDisabled} />
          </div>
        ) : null}

        {children}
      </div>
    </SectionCard>
  )
}
