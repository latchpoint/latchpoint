import { useQueryClient } from '@tanstack/react-query'
import { AlarmPanel } from '@/components/alarm'
import { SystemStatusCard } from '@/components/dashboard/SystemStatusCard'
import { Page } from '@/components/layout'
import { FeatureErrorBoundary } from '@/components/providers/FeatureErrorBoundary'
import { queryKeys } from '@/types'

export function DashboardPage() {
  const queryClient = useQueryClient()

  const handleAlarmRetry = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.alarm.state })
    void queryClient.invalidateQueries({ queryKey: queryKeys.sensors.all })
    void queryClient.invalidateQueries({ queryKey: queryKeys.events.recent })
  }

  return (
    <Page title="Home" description="Arm/disarm and review recent activity.">
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <FeatureErrorBoundary feature="Latchpoint" onRetry={handleAlarmRetry}>
            <AlarmPanel />
          </FeatureErrorBoundary>
        </div>
        <div className="space-y-6">
          <FeatureErrorBoundary feature="System Status" variant="inline">
            <SystemStatusCard />
          </FeatureErrorBoundary>
        </div>
      </div>
    </Page>
  )
}

export default DashboardPage
