import type { AlarmStateType } from '@/lib/constants'
import type { AlarmEvent, CountdownPayload, Sensor } from '@/types'
import { cn } from '@/lib/utils'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { AlarmStatus } from './AlarmStatus'
import { ArmButtons } from './ArmButtons'
import { CountdownTimer } from './CountdownTimer'
import { QuickActions } from './QuickActions'
import { AlarmHistory } from './AlarmHistory'

export interface AlarmPanelViewProps {
  className?: string

  // State
  currentState: AlarmStateType
  countdown: CountdownPayload | null
  isArmed: boolean
  isDisarmed: boolean
  isArming: boolean
  isPending: boolean
  isTriggered: boolean
  availableArmingStates: AlarmStateType[]
  isLoading: boolean

  // Data
  recentEvents: AlarmEvent[]
  openSensors: Sensor[]
  unknownSensors: Sensor[]

  // Callbacks
  onArm: (targetState: AlarmStateType) => void
  onDisarm: () => void
  onCancelArming: () => void
}

/**
 * Pure presentation component for the alarm panel.
 * Receives all data and callbacks via props - no hooks, no state management.
 */
export function AlarmPanelView({
  className,
  currentState,
  countdown,
  isArmed,
  isDisarmed,
  isArming,
  isPending,
  isTriggered,
  availableArmingStates,
  isLoading,
  recentEvents,
  openSensors,
  unknownSensors,
  onArm,
  onDisarm,
  onCancelArming,
}: AlarmPanelViewProps) {
  return (
    <div className={cn('space-y-6', className)}>
      {/* Main Status Card */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-col items-center">
            {/* Countdown Timer (if active) */}
            {countdown && (isArming || isPending || isTriggered) && (
              <div className="w-full mb-6">
                <CountdownTimer
                  remainingSeconds={countdown.remainingSeconds}
                  totalSeconds={countdown.totalSeconds}
                  type={countdown.type}
                />
              </div>
            )}

            {/* Alarm Status */}
            {!countdown && (
              <AlarmStatus state={currentState} size="xl" animate={isTriggered} />
            )}

            {/* Action Buttons based on state */}
            <div className="w-full mt-6">
              {isDisarmed && (
                <div className="space-y-3">
                  {(openSensors.length > 0 || unknownSensors.length > 0) && (
                    <div className="rounded-lg border p-3 text-sm">
                      <div className="font-medium">Arming warnings</div>
                      <ul className="mt-2 space-y-1 text-muted-foreground">
                        {openSensors.length > 0 && (
                          <li>
                            {openSensors.length} sensor{openSensors.length === 1 ? '' : 's'} open
                            {' '}({openSensors.slice(0, 2).map((s) => s.name).join(', ')}
                            {openSensors.length > 2 ? ', …' : ''})
                          </li>
                        )}
                        {unknownSensors.length > 0 && (
                          <li>
                            {unknownSensors.length} sensor{unknownSensors.length === 1 ? '' : 's'} unavailable
                            {' '}({unknownSensors.slice(0, 2).map((s) => s.name).join(', ')}
                            {unknownSensors.length > 2 ? ', …' : ''})
                          </li>
                        )}
                        <li>Arming is still allowed, but behavior may be unexpected.</li>
                      </ul>
                    </div>
                  )}

                  <ArmButtons
                    onArm={onArm}
                    availableStates={availableArmingStates}
                    currentState={currentState}
                    disabled={isLoading}
                  />
                </div>
              )}

              {isArming && (
                <QuickActions
                  onDisarm={onDisarm}
                  onCancel={onCancelArming}
                  showCancel={true}
                  showDisarm={true}
                  showPanic={false}
                  disabled={isLoading}
                />
              )}

              {(isArmed || isPending || isTriggered) && (
                <QuickActions
                  onDisarm={onDisarm}
                  showDisarm={true}
                  showPanic={isTriggered}
                  disabled={isLoading}
                />
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Recent Activity Card */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg">Recent Activity</CardTitle>
        </CardHeader>
        <CardContent>
          <AlarmHistory events={recentEvents} maxItems={5} />
        </CardContent>
      </Card>
    </div>
  )
}
