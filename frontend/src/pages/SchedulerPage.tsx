import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Info } from 'lucide-react'

import { Page } from '@/components/layout'
import { SettingsTabShell } from '@/features/settings/components/SettingsTabShell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { LoadingInline } from '@/components/ui/loading-inline'
import { Tooltip } from '@/components/ui/tooltip'
import { schedulerService } from '@/services'
import { TEN_SECONDS_MS, UserRole } from '@/lib/constants'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import type { SchedulerTaskHealth } from '@/types'

const TASK_DESCRIPTION_OVERRIDES: Record<string, string> = {
  broadcast_system_status: 'Keeps the app up to date with the latest connection status of your integrations.',
  check_home_assistant: 'Checks whether Home Assistant is reachable, so the app can show an accurate status.',
  cleanup_expired_sessions: 'Removes expired login sessions to keep things running smoothly.',
  cleanup_frigate_detections: 'Deletes old camera detections based on your configured retention settings.',
  cleanup_old_events: 'Deletes old alarm history entries based on your retention settings.',
  cleanup_orphan_rule_entity_refs: 'Cleans up stale rule references to devices that no longer exist.',
  cleanup_rule_action_logs: 'Deletes old rule activity logs based on your retention settings.',
  notifications_send_pending: 'Sends pending notifications and retries temporary failures.',
  process_due_rule_runtimes: 'Completes “wait for X seconds” rule timers and triggers any rules that become due.',
  scheduler_cleanup_task_runs: 'Cleans up old scheduler history so it doesn’t grow without limits.',
  sync_entity_states: 'Refreshes device states from Home Assistant when available.',
}

function formatDateTime(value: string | null): string {
  if (!value) return '—'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString()
}

function formatSeconds(value: number | null): string {
  if (value === null || value === undefined) return '—'
  if (!Number.isFinite(value)) return '—'
  if (value < 1) return `${Math.round(value * 1000)}ms`
  return `${value.toFixed(2)}s`
}

function formatTaskName(taskName: string): string {
  const cleaned = taskName.trim().replace(/-/g, '_').replace(/__+/g, '_')
  const words = cleaned.split('_').filter(Boolean)
  const titled = words.map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
  return titled
    .replace(/\bMqtt\b/g, 'MQTT')
    .replace(/\bZwavejs\b/g, 'Z-Wave JS')
    .replace(/\bZigbee2mqtt\b/g, 'Zigbee2MQTT')
    .replace(/\bHa\b/g, 'HA')
    .replace(/\bWs\b/g, 'WS')
    .replace(/\bId\b/g, 'ID')
}

function statusBadgeVariant(status: SchedulerTaskHealth['status']): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'ok') return 'outline'
  if (status === 'never_ran') return 'outline'
  if (status === 'orphaned') return 'secondary'
  if (status === 'running') return 'secondary'
  if (status === 'disabled') return 'default'
  return 'destructive'
}

function formatEnabledReason(reason: string | null | undefined): string | null {
  if (!reason) return null
  if (reason === 'gated') return 'gated (integration inactive)'
  if (reason === 'gating_error') return 'gating error'
  if (reason === 'disabled') return 'disabled'
  return reason
}

function formatStatusLabel(status: SchedulerTaskHealth['status'], enabledReason: string | null | undefined): string {
  if (status === 'never_ran') return 'never ran'
  if (status === 'orphaned') return 'orphaned'
  if (status === 'disabled') {
    if (enabledReason === 'gated') return 'gated'
    if (enabledReason === 'gating_error') return 'gating error'
    return 'disabled'
  }
  return status
}

export function SchedulerPage() {
  const { data: user } = useCurrentUserQuery()
  const isAdmin = user?.role === UserRole.ADMIN

  const [selectedTaskName, setSelectedTaskName] = useState<string | null>(null)

  const statusQuery = useQuery({
    queryKey: ['scheduler', 'status'],
    enabled: isAdmin,
    queryFn: () => schedulerService.getStatus(),
    refetchInterval: TEN_SECONDS_MS,
  })

  const tasks = statusQuery.data?.tasks ?? []
  const selectedTask = useMemo(
    () => tasks.find((t) => t.taskName === selectedTaskName) ?? null,
    [tasks, selectedTaskName]
  )

  const runsQuery = useQuery({
    queryKey: ['scheduler', 'runs', selectedTaskName],
    enabled: isAdmin && Boolean(selectedTaskName),
    queryFn: () => schedulerService.getTaskRuns(selectedTaskName || '', { page: 1 }),
  })

  const loadError = statusQuery.error ? (statusQuery.error as Error).message : null

  return (
    <Page title="Scheduler" description="Monitor scheduled tasks and recent failures.">
      <SettingsTabShell
        isAdmin={isAdmin}
        adminMessage="Admin role required to view scheduler status."
        loadError={loadError}
        showAdminBanner={!isAdmin}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="text-sm text-muted-foreground">
            Instance: <span className="font-mono">{statusQuery.data?.instanceId ?? '—'}</span>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => statusQuery.refetch()}
            disabled={!isAdmin || statusQuery.isFetching}
          >
            Refresh
          </Button>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Tasks</CardTitle>
          </CardHeader>
          <CardContent>
            {statusQuery.isLoading ? <LoadingInline label="Loading scheduler status…" /> : null}

            {!statusQuery.isLoading && tasks.length === 0 ? (
              <div className="text-sm text-muted-foreground">No task status available yet.</div>
            ) : null}

            {tasks.length ? (
              <div className="space-y-2">
                <div className="hidden sm:grid sm:grid-cols-12 text-xs text-muted-foreground px-2">
                  <div className="col-span-4">Task</div>
                  <div className="col-span-2">Status</div>
                  <div className="col-span-2">Next run</div>
                  <div className="col-span-2">Last run</div>
                  <div className="col-span-1">Duration</div>
                  <div className="col-span-1">Fails</div>
                </div>
                {tasks.map((task) => {
                  const isSelected = task.taskName === selectedTaskName
                  const tooltipContent =
                    TASK_DESCRIPTION_OVERRIDES[task.taskName] ||
                    task.description ||
                    'No description available.'
                  const name = task.displayName || formatTaskName(task.taskName)
                  const enabledReason = formatEnabledReason(task.enabledReason)
                  const statusLabel = formatStatusLabel(task.status, task.enabledReason)
                  return (
                    <button
                      key={`${task.instanceId}:${task.taskName}`}
                      type="button"
                      onClick={() => setSelectedTaskName(task.taskName)}
                      className={[
                        'w-full text-left rounded-md border px-2 py-2',
                        'hover:bg-accent hover:text-accent-foreground transition-colors',
                        isSelected ? 'bg-accent text-accent-foreground' : 'bg-card',
                      ].join(' ')}
                    >
                      <div className="grid grid-cols-1 sm:grid-cols-12 gap-2 items-center">
                        <div className="sm:col-span-4 text-sm flex items-center gap-2">
                          <div className="min-w-0 truncate">{name}</div>
                          <Tooltip content={tooltipContent} side="right">
                            <span
                              className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground"
                              aria-label="Task description"
                            >
                              <Info className="h-4 w-4" />
                            </span>
                          </Tooltip>
                        </div>
                        <div className="sm:col-span-2">
                          <Badge variant={statusBadgeVariant(task.status)}>{statusLabel}</Badge>
                          {task.status === 'disabled' && enabledReason ? (
                            <div className="text-xs text-muted-foreground mt-1">{enabledReason}</div>
                          ) : null}
                        </div>
                        <div className="sm:col-span-2 text-sm">{formatDateTime(task.nextRunAt)}</div>
                        <div className="sm:col-span-2 text-sm">{formatDateTime(task.lastFinishedAt)}</div>
                        <div className="sm:col-span-1 text-sm">{formatSeconds(task.lastDurationSeconds)}</div>
                        <div className="sm:col-span-1 text-sm">{task.consecutiveFailures}</div>
                      </div>
                    </button>
                  )
                })}
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Details</CardTitle>
          </CardHeader>
          <CardContent>
            {!selectedTask ? (
              <div className="text-sm text-muted-foreground">Select a task to see details and recent runs.</div>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <div className="min-w-0 truncate text-sm">
                    {selectedTask.displayName || formatTaskName(selectedTask.taskName)}
                  </div>
                  <Badge variant={statusBadgeVariant(selectedTask.status)}>
                    {formatStatusLabel(selectedTask.status, selectedTask.enabledReason)}
                  </Badge>
                </div>
                <div className="text-muted-foreground text-xs">
                  {TASK_DESCRIPTION_OVERRIDES[selectedTask.taskName] ||
                    selectedTask.description ||
                    'No description available.'}
                </div>
                {selectedTask.status === 'disabled' && formatEnabledReason(selectedTask.enabledReason) ? (
                  <div className="text-muted-foreground text-xs">
                    Disabled reason: {formatEnabledReason(selectedTask.enabledReason)}
                  </div>
                ) : null}
                {selectedTask.lastErrorMessage ? (
                  <div className="text-sm">
                    <div className="text-muted-foreground text-xs mb-1">Last error</div>
                    <div className="font-mono text-xs whitespace-pre-wrap">{selectedTask.lastErrorMessage}</div>
                  </div>
                ) : null}
                {selectedTask.status === 'stuck' && selectedTask.stuckForSeconds !== null ? (
                  <div className="text-sm text-destructive">
                    Stuck for ~{selectedTask.stuckForSeconds}s (max runtime {selectedTask.maxRuntimeSeconds}s)
                  </div>
                ) : null}

                <div className="pt-2">
                  <div className="text-muted-foreground text-xs mb-2">Recent runs</div>
                  {runsQuery.isLoading ? <LoadingInline label="Loading runs…" /> : null}
                  {!runsQuery.isLoading && runsQuery.data?.data?.length ? (
                    <div className="space-y-1">
                      {runsQuery.data.data.slice(0, 10).map((run) => (
                        <div
                          key={run.id}
                          className="rounded-md border px-2 py-2 text-sm grid grid-cols-1 sm:grid-cols-12 gap-2"
                        >
                          <div className="sm:col-span-3 font-mono text-xs">{formatDateTime(run.startedAt)}</div>
                          <div className="sm:col-span-2">
                            <Badge variant={run.status === 'failure' ? 'destructive' : 'outline'}>{run.status}</Badge>
                          </div>
                          <div className="sm:col-span-2 text-xs">{formatSeconds(run.durationSeconds)}</div>
                          <div className="sm:col-span-5 font-mono text-xs truncate">
                            {run.errorMessage ? run.errorMessage : '—'}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {!runsQuery.isLoading && !runsQuery.data?.data?.length ? (
                    <div className="text-sm text-muted-foreground">No runs recorded yet.</div>
                  ) : null}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </SettingsTabShell>
    </Page>
  )
}

export default SchedulerPage
