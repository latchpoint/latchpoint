import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'

interface CountdownTimerProps {
  remainingSeconds: number
  totalSeconds: number
  type: 'entry' | 'exit' | 'trigger'
  className?: string
  onComplete?: () => void
}

const typeConfig = {
  entry: {
    label: 'Entry Delay',
    bgColor: 'bg-warning',
    textColor: 'text-warning',
    progressColor: 'bg-warning/80',
  },
  exit: {
    label: 'Exit Delay',
    bgColor: 'bg-warning',
    textColor: 'text-warning',
    progressColor: 'bg-warning/80',
  },
  trigger: {
    label: 'Alarm Active',
    bgColor: 'bg-critical',
    textColor: 'text-critical',
    progressColor: 'bg-danger',
  },
}

export function CountdownTimer({
  remainingSeconds,
  totalSeconds,
  type,
  className,
  onComplete,
}: CountdownTimerProps) {
  const [displaySeconds, setDisplaySeconds] = useState(remainingSeconds)
  const config = typeConfig[type]
  const progress = totalSeconds > 0 ? ((totalSeconds - displaySeconds) / totalSeconds) * 100 : 0

  // Sync with prop changes
  useEffect(() => {
    setDisplaySeconds(remainingSeconds)
  }, [remainingSeconds])

  // Local countdown for smooth animation
  useEffect(() => {
    if (displaySeconds <= 0) {
      onComplete?.()
      return
    }

    const timer = setInterval(() => {
      setDisplaySeconds((prev) => {
        if (prev <= 1) {
          onComplete?.()
          return 0
        }
        return prev - 1
      })
    }, 1000)

    return () => clearInterval(timer)
  }, [displaySeconds, onComplete])

  // Format time as MM:SS if over 60 seconds
  const formatTime = (seconds: number): string => {
    if (seconds >= 60) {
      const mins = Math.floor(seconds / 60)
      const secs = seconds % 60
      return `${mins}:${secs.toString().padStart(2, '0')}`
    }
    return seconds.toString()
  }

  // Determine urgency for styling
  const isUrgent = displaySeconds <= 10
  const isCritical = displaySeconds <= 5

  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-xl p-6',
        config.bgColor,
        className
      )}
    >
      {/* Progress bar background */}
      <div
        className={cn(
          'absolute inset-0 transition-all duration-1000 ease-linear',
          config.progressColor
        )}
        style={{ width: `${progress}%` }}
      />

      {/* Content */}
      <div className="relative z-10 flex flex-col items-center text-white">
        <p className="text-sm font-medium opacity-90">{config.label}</p>
        <p
          className={cn(
            'text-6xl font-bold tabular-nums transition-transform',
            isUrgent && 'scale-110',
            isCritical && 'animate-pulse'
          )}
        >
          {formatTime(displaySeconds)}
        </p>
        <p className="text-sm opacity-75 mt-1">seconds remaining</p>
      </div>

      {/* Urgency indicator */}
      {isCritical && (
        <div className="absolute inset-0 animate-ping bg-white/10 rounded-xl" />
      )}
    </div>
  )
}

export default CountdownTimer
